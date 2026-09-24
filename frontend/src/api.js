const BASE = '/api'

// 行动请求并发控制：
// - expectedRev：当前视口的存档版本号，服务端据此拒绝基于过期状态的提交（409 状态冲突）
// - 每个新意图生成 request_id 做请求级幂等；网络超时后的同一重试复用同一 id，
//   服务端返回首次结果，不会重复扣款/发奖（双击/重复请求同理）
let expectedRev = null

export function setExpectedRev(rev) {
  if (Number.isInteger(rev)) expectedRev = rev
}

// 多人协作远征：当前成员身份 {party_id, member_id, token, role}（从大厅/本地存储
// 恢复）。设置后，所有章节 run 的动作与推进章节请求自动携带凭据，服务端按角色
// 鉴权；单人局为 null，请求形态与旧版完全一致。
let coopMember = null

export function setCoopMember(member) {
  coopMember = member || null
}

export function getCoopMember() {
  return coopMember
}

export class ConflictError extends Error {
  constructor(detail) {
    super(detail || '状态已变化，请刷新后重试')
    this.status = 409
  }
}

export class ForbiddenError extends Error {
  constructor(detail) {
    super(detail || '你的角色无权执行该操作')
    this.status = 403
  }
}

let reqSeq = 0
function newRequestId() {
  reqSeq += 1
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return `${Date.now().toString(36)}-${crypto.randomUUID().slice(0, 8)}`
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}-${reqSeq}`
}

async function j(url, opts) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    if (res.status === 409) throw new ConflictError(data.detail)
    if (res.status === 403) throw new ForbiddenError(data.detail)
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return data
}

export const api = {
  cards: () => j(`${BASE}/cards`),
  async createRun(seed) {
    const data = await j(`${BASE}/runs`, { method: 'POST', body: JSON.stringify({ seed }) })
    setExpectedRev(data.rev)
    return data
  },
  async resume(id) {
    const data = await j(`${BASE}/runs/${id}/resume`)
    setExpectedRev(data.rev)
    return data
  },
  replay: (id) => j(`${BASE}/runs/${id}/replay`),

  // ---------- 多章远征 ----------
  async createExpedition(seed, chapters) {
    const data = await j(`${BASE}/expeditions`, {
      method: 'POST',
      body: JSON.stringify({ seed, chapters }),
    })
    if (Number.isInteger(data.run?.rev)) setExpectedRev(data.run.rev)
    return data
  },
  async getExpedition(id) {
    const data = await j(`${BASE}/expeditions/${id}`)
    if (Number.isInteger(data.run?.rev)) setExpectedRev(data.run.rev)
    return data
  },
  expeditionReplay: (id) => j(`${BASE}/expeditions/${id}/replay`),
  async advanceExpedition(id, { retryKey, member } = {}) {
    // 与 run 行动同理：request_id 幂等，重复/并发提交返回首次结果，不会重复开章
    // 协作远征：队长凭据（全局协作身份即队长时自动携带）
    const cred = member !== undefined ? member : coopMember
    const requestId = retryKey || newRequestId()
    const data = await j(`${BASE}/expeditions/${id}/advance`, {
      method: 'POST',
      body: JSON.stringify({
        request_id: requestId,
        ...(cred?.member_id && cred.token
          ? { member_id: cred.member_id, token: cred.token }
          : {}),
      }),
    })
    if (Number.isInteger(data.run?.rev)) setExpectedRev(data.run.rev)
    return data
  },

  act: async (id, action, { retryKey, member } = {}) => {
    // retryKey：调用方在“重试同一个意图”时显式传入；缺省每个调用一个新令牌
    // member 默认用全局协作身份（大厅进入远征时设置）；单人局为 null
    const cred = member !== undefined ? member : coopMember
    const requestId = retryKey || newRequestId()
    const body = { ...action, request_id: requestId }
    if (cred?.member_id && cred?.token) {
      body.member_id = cred.member_id
      body.token = cred.token
    }
    if (expectedRev !== null) body.expected_rev = expectedRev
    try {
      const data = await j(`${BASE}/runs/${id}/act`, { method: 'POST', body: JSON.stringify(body) })
      if (Number.isInteger(data.rev)) expectedRev = data.rev
      return data
    } catch (e) {
      // 状态冲突：版本号已失效，清掉避免后续请求继续带旧值；调用方应刷新续局
      if (e instanceof ConflictError) expectedRev = null
      throw e
    }
  },

  // ---------- 多人协作远征 ----------
  createParty: (name, seed) => j(`${BASE}/coop/parties`, {
    method: 'POST',
    body: JSON.stringify({ name, seed: seed || undefined }),
  }),
  joinParty: (code, name, rejoin) => j(`${BASE}/coop/parties/join`, {
    method: 'POST',
    body: JSON.stringify({
      code, name,
      ...(rejoin ? { member_id: rejoin.member_id, token: rejoin.token } : {}),
    }),
  }),
  partyStatus: (partyId, member) => j(
    `${BASE}/coop/parties/${partyId}?member_id=${encodeURIComponent(member.member_id)}`
    + `&token=${encodeURIComponent(member.token)}`),
  setPartyRole: (partyId, member, targetId, role) => j(
    `${BASE}/coop/parties/${partyId}/role`, {
      method: 'POST',
      body: JSON.stringify({
        member_id: member.member_id, token: member.token,
        target_id: targetId, role,
      }),
    }),
  leaveParty: (partyId, member) => j(`${BASE}/coop/parties/${partyId}/leave`, {
    method: 'POST',
    body: JSON.stringify({ member_id: member.member_id, token: member.token }),
  }),
  async startParty(partyId, member, chapters) {
    const data = await j(`${BASE}/coop/parties/${partyId}/start`, {
      method: 'POST',
      body: JSON.stringify({
        member_id: member.member_id, token: member.token,
        chapters, request_id: newRequestId(),
      }),
    })
    if (Number.isInteger(data.run?.rev)) setExpectedRev(data.run.rev)
    return data
  },
  partyReplay: (partyId) => j(`${BASE}/coop/parties/${partyId}/replay`),
}

// 统一的行动错误处理：遇到 409（重复请求/状态冲突）自动拉取最新视口对齐，
// 返回可展示给用户的提示语。refresh 为最新视口应用函数（通常是 applyRun）。
// 403（协作远征越权/令牌错误）不刷新视口，直接展示角色边界提示。
export async function handleActError(e, runId, refresh) {
  if (e instanceof ConflictError) {
    try {
      const fresh = await api.resume(runId)
      if (refresh) refresh(fresh)
    } catch (_) { /* 刷新失败仅保留提示 */ }
    return '操作与最新状态冲突，已自动刷新，请重试'
  }
  if (e instanceof ForbiddenError) {
    return `⛔ ${e.message}`
  }
  return e.message
}
