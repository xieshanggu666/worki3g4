import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, ForbiddenError } from '../api'

// 多人协作远征 · 组队大厅：
// 队长建队 -> 分享 6 位邀请码 -> 成员加入 -> 队长分配战斗/资源位 -> 队长开征。
// 成员身份（member_id/token）保存在 localStorage，刷新页面可凭码+令牌回到队伍。
const STORE_KEY = 'cardrun.coop.me'

function loadMe() {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch (_) {
    return null
  }
}

export default function CoopLobby({ onStarted }) {
  const [party, setParty] = useState(null)
  const [myName, setMyName] = useState(loadMe()?.name || '')
  const [createName, setCreateName] = useState('')
  const [joinCode, setJoinCode] = useState('')
  const [joinName, setJoinName] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [chapters, setChapters] = useState('3')
  const pollRef = useRef(null)

  const persistMe = useCallback((view) => {
    const me = {
      party_id: view.id,
      party_status: view.status,
      expedition_id: view.expedition_id,
      member_id: view.me.member_id,
      token: view.me.token,
      role: view.me.role,
      name: view.me.name,
    }
    localStorage.setItem(STORE_KEY, JSON.stringify(me))
    return me
  }, [])

  const refresh = useCallback(async () => {
    const me = loadMe()
    if (!me?.party_id) return
    try {
      const view = await api.partyStatus(me.party_id, me)
      setParty(view)
    } catch (e) {
      if (e instanceof ForbiddenError) localStorage.removeItem(STORE_KEY)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // 大厅阶段轮询：成员加入/角色变更/开征对所有队员实时可见
  useEffect(() => {
    if (!party || party.status !== 'forming') return
    pollRef.current = setInterval(refresh, 1500)
    return () => clearInterval(pollRef.current)
  }, [party?.status, party?.rev, refresh])

  async function run(label, fn) {
    setBusy(true); setErr('')
    try { return await fn() } catch (e) { setErr(`${label}：${e.message}`) }
    finally { setBusy(false) }
  }

  async function create() {
    const name = (createName || myName || '队长').trim()
    const view = await run('创建队伍', () => api.createParty(name))
    if (view) { persistMe(view); setParty(view); setMyName(view.me.name) }
  }

  async function join(rejoin = false) {
    const saved = loadMe()
    const view = await run('加入队伍', () => api.joinParty(
      joinCode.trim().toUpperCase(),
      (joinName || myName || '队员').trim(),
      rejoin && saved ? saved : null))
    if (view) { persistMe(view); setParty(view); setMyName(view.me.name) }
  }

  async function rejoinByCode() {
    const saved = loadMe()
    if (!saved) { setErr('请先输入邀请码与昵称加入') ; return }
    const view = await run('回到队伍', () => api.joinParty(
      joinCode.trim().toUpperCase(), saved.name, saved))
    if (view) { persistMe(view); setParty(view) }
  }

  async function setRole(target, role) {
    const me = loadMe()
    const view = await run('调整角色', () =>
      api.setPartyRole(party.id, me, target, role))
    if (view) setParty(view)
  }

  async function leave() {
    const me = loadMe()
    const res = await run('离开队伍', () => api.leaveParty(party.id, me))
    if (res) {
      localStorage.removeItem(STORE_KEY)
      setParty(null)
    }
  }

  async function start() {
    const me = loadMe()
    const data = await run('开启远征', () =>
      api.startParty(party.id, me, chapters ? Number(chapters) : undefined))
    if (data) {
      const stored = persistMe({
        id: party.id, status: 'active', expedition_id: data.expedition.id,
        me: { member_id: me.member_id, token: me.token, role: me.role, name: me.name },
      })
      onStarted?.(data, stored)
    }
  }

  const me = loadMe()
  const isLeader = party?.me?.role === 'leader' || me?.role === 'leader'

  if (party) {
    return (
      <div className="coop-lobby panel">
        <h2>🛡️ 协作队伍 {party.status === 'forming' && <span className="tag forming">组队中</span>}</h2>
        {party.status === 'forming' && (
          <div className="coop-join-code">
            邀请码：<b>{party.join_code}</b>
            <button className="mini" onClick={() => navigator.clipboard?.writeText(party.join_code)}>
              复制
            </button>
            <span className="sub">把邀请码发给队友，在此页面等待加入</span>
          </div>
        )}
        <ul className="coop-members">
          {party.members.map((m) => (
            <li key={m.member_id} className={`coop-member role-${m.role}`}>
              <span className="coop-name">
                {m.name}
                {m.member_id === party.leader_id && ' 👑'}
                {m.member_id === me?.member_id && <span className="sub">（我）</span>}
              </span>
              <span className={`chip role-chip ${m.role}`}>{m.role_label}</span>
              {isLeader && party.status === 'forming' && m.role !== 'leader' && (
                <span className="coop-role-btns">
                  <button className={`mini ${m.role === 'battle' ? 'on' : ''}`}
                          disabled={busy || m.role === 'battle'}
                          onClick={() => setRole(m.member_id, 'battle')}>战斗位</button>
                  <button className={`mini ${m.role === 'supply' ? 'on' : ''}`}
                          disabled={busy || m.role === 'supply'}
                          onClick={() => setRole(m.member_id, 'supply')}>资源位</button>
                </span>
              )}
            </li>
          ))}
        </ul>
        <p className="sub">
          {party.members.length}/{party.max_members} 人 · 至少 {party.min_members} 人开征 ·
          战斗位负责打牌/回合/战斗药水，资源位负责选路/领奖/锻造/商店/委托/奇遇，队长可执行任何操作并推进章节
        </p>
        {party.status === 'forming' && (
          <div className="fieldrow">
            <span>章节</span>
            <input value={chapters} onChange={(e) => setChapters(e.target.value)}
                   disabled={!isLeader || busy} style={{ width: 64 }} />
            {isLeader ? (
              <button className="primary" disabled={busy || party.members.length < party.min_members}
                      onClick={start}>
                {party.members.length < party.min_members
                  ? `还差 ${party.min_members - party.members.length} 人` : '🚩 队长开征'}
              </button>
            ) : (
              <span className="tag waiting">等待队长开征…</span>
            )}
            <button disabled={busy} onClick={leave}>退出队伍</button>
          </div>
        )}
        {err && <div className="error">{err}</div>}
      </div>
    )
  }

  return (
    <div className="coop-lobby panel">
      <h2>🛡️ 多人协作远征</h2>
      <p className="sub">2–4 名玩家组队：队长组建队伍，战斗位与资源位分头操作，共享章节状态、同步结算。</p>
      <div className="fieldrow">
        <span>队长昵称</span>
        <input value={createName} onChange={(e) => setCreateName(e.target.value)}
               placeholder={myName || '队长'} />
        <button className="primary" disabled={busy} onClick={create}>组建队伍</button>
      </div>
      <div className="divider" />
      <div className="fieldrow">
        <span>邀请码</span>
        <input value={joinCode} onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
               placeholder="6 位码" maxLength={6} style={{ width: 100 }} />
        <span>昵称</span>
        <input value={joinName} onChange={(e) => setJoinName(e.target.value)}
               placeholder={myName || '队员'} />
        <button disabled={busy || joinCode.length < 6} onClick={() => join(false)}>加入队伍</button>
        {me && <button disabled={busy || joinCode.length < 6} onClick={rejoinByCode}>回到我的队伍</button>}
      </div>
      {err && <div className="error">{err}</div>}
    </div>
  )
}
