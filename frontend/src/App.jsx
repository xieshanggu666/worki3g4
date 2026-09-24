import React, { useEffect, useState } from 'react'
import { api, setCoopMember } from './api'
import { useStore } from './store'
import MapView from './components/MapView.jsx'
import BattleView from './components/BattleView.jsx'
import RewardView from './components/RewardView.jsx'
import ForgeView from './components/ForgeView.jsx'
import ShopView from './components/ShopView.jsx'
import DeckView from './components/DeckView.jsx'
import CommissionPanel from './components/CommissionPanel.jsx'
import PotionBelt from './components/PotionBelt.jsx'
import CompanionPanel from './components/CompanionPanel.jsx'
import EncounterView from './components/EncounterView.jsx'
import EncounterFlags from './components/EncounterFlags.jsx'
import ReplayPlayer from './components/ReplayPlayer.jsx'
import ExpeditionReplay from './components/ExpeditionReplay.jsx'
import CoopLobby from './components/CoopLobby.jsx'
import CoopRoster from './components/CoopRoster.jsx'
import CoopReplay from './components/CoopReplay.jsx'

export default function App() {
  const { view, setCards, cards, runId, setRunId, applyRun } = useStore()
  const [seed, setSeed] = useState('')
  const [resumeId, setResumeId] = useState('')
  const [expChapters, setExpChapters] = useState('3')
  const [expId, setExpId] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  // 商店面板仅在本地收起：再次进入节点或点击“回到商店”重开（不发任何交易动作）
  const [shopDismissed, setShopDismissed] = useState(false)
  // 整局回放：replayId 非 null 时覆盖全屏播放器（严格只读，与当前对局隔离）
  const [replayId, setReplayId] = useState(null)
  // 远征整程回放：expReplayId 非 null 时覆盖全屏（逐章切换，同样只读隔离）
  const [expReplayId, setExpReplayId] = useState(null)
  // 多人协作：本地保存的成员身份（member_id/token），有协作远征进行时显示续征入口
  const [coopMe] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('cardrun.coop.me') || 'null')
    } catch (_) {
      return null
    }
  })
  const [coopPartyId, setCoopPartyId] = useState(null)
  const [coopReplayId, setCoopReplayId] = useState(null)

  // 协作远征进行中（上次会话）：直接挂载凭据并续征
  async function resumeCoopExpedition() {
    if (!coopMe?.expedition_id) return
    setLoading(true); setErr('')
    try {
      setCoopMember(coopMe)
      const data = await api.getExpedition(coopMe.expedition_id)
      applyRun(data.run)
      setRunId(data.run.run_id)
      setCoopPartyId(coopMe.party_id)
      setCoopReplayId(coopMe.party_id)
      setReplayId(null)
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  function onCoopStarted(data, stored) {
    setCoopMember(stored)
    applyRun(data.run)
    setRunId(data.run.run_id)
    setCoopPartyId(stored.party_id)
    setCoopReplayId(stored.party_id)
  }

  const inCoop = !!view?.coop

  useEffect(() => {
    api.cards().then(setCards).catch(() => {})
  }, [])

  // 切换到不同节点（进商店/离开商店/续局）时重置商店面板的本地收起状态
  useEffect(() => {
    setShopDismissed(false)
  }, [view?.position, runId])

  async function create() {
    setLoading(true); setErr('')
    try {
      setCoopMember(null)
      const run = await api.createRun(seed ? Number(seed) : undefined)
      applyRun(run)
      setRunId(run.run_id)
      setCoopPartyId(null)
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function resume() {
    if (!resumeId) return
    setLoading(true); setErr('')
    try {
      setCoopMember(null)
      const run = await api.resume(resumeId)
      applyRun(run)
      setRunId(run.run_id)
      setReplayId(null)
      setCoopPartyId(null)
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  function openReplay(id) {
    const target = (id || runId || '').trim()
    if (target) setReplayId(target)
  }

  async function createExpedition() {
    setLoading(true); setErr('')
    try {
      const chapters = expChapters ? Number(expChapters) : undefined
      setCoopMember(null)
      const data = await api.createExpedition(seed ? Number(seed) : undefined, chapters)
      applyRun(data.run)
      setRunId(data.run.run_id)
      setCoopPartyId(null)
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function resumeExpedition(id) {
    const target = (id || expId || '').trim()
    if (!target) return
    setLoading(true); setErr('')
    try {
      setCoopMember(null)
      const data = await api.getExpedition(target)
      applyRun(data.run)
      setRunId(data.run.run_id)
      setReplayId(null)
      setCoopPartyId(null)
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  function openExpeditionReplay(id) {
    const target = (id || view?.expedition?.id || expId || '').trim()
    if (target) setExpReplayId(target)
  }

  async function advanceChapter() {
    const expeditionId = view?.expedition?.id
    if (!expeditionId) return
    setLoading(true); setErr('')
    try {
      const data = await api.advanceExpedition(expeditionId)
      applyRun(data.run)
      setRunId(data.run.run_id)
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function refreshRun() {
    if (!runId) return
    setErr('')
    try {
      const run = await api.resume(runId)
      applyRun(run)
    } catch (e) {
      setErr(e.message)
    }
  }

  async function newRun() {
    setErr('')
    setCoopMember(null)
    setCoopPartyId(null)
    const run = await api.createRun()
    applyRun(run)
    setRunId(run.run_id)
  }

  // 章节通关结算遮罩内领取委托奖励（与侧栏面板同接口、request_id 幂等）
  async function claimCommission(cid) {
    if (!runId) return
    setLoading(true); setErr('')
    try {
      const res = await api.act(runId, { action: 'commission_claim', commission: cid })
      applyRun(res.run)
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  if (!view) {
    return (
      <div className="screen home">
        <div className="panel">
          <h1>卡牌闯关</h1>
          <p>选择路线 · 构筑牌组 · 挑战首领 · 失败解锁新卡</p>
          <div className="fieldrow">
            <span>种子（可选）</span>
            <input value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="随机" />
          </div>
          <button className="primary" onClick={create} disabled={loading}>
            {loading ? '创建中…' : '新建一局（随机种子）'}
          </button>
          <div className="divider" />
          <div className="fieldrow">
            <span>远征章节</span>
            <input value={expChapters} onChange={(e) => setExpChapters(e.target.value)} placeholder="3" />
            <button className="primary" onClick={createExpedition} disabled={loading}>
              {loading ? '创建中…' : '🚩 新建远征（多章连征）'}
            </button>
          </div>
          <div className="fieldrow">
            <span>远征 ID</span>
            <input value={expId} onChange={(e) => setExpId(e.target.value)} placeholder="粘贴 expedition_id" />
            <button onClick={() => resumeExpedition()} disabled={loading || !expId}>续远征</button>
            <button onClick={() => openExpeditionReplay()} disabled={loading || !expId}>🎬 整程回放</button>
          </div>
          <div className="divider" />
          <CoopLobby onStarted={onCoopStarted} />
          {coopMe?.expedition_id && (
            <div className="fieldrow">
              <button className="primary" onClick={resumeCoopExpedition} disabled={loading}>
                🛡️ 回到协作远征（{coopMe.name}）
              </button>
            </div>
          )}
          <div className="divider" />
          <div className="fieldrow">
            <span>续局 ID</span>
            <input value={resumeId} onChange={(e) => setResumeId(e.target.value)} placeholder="粘贴 run_id" />
            <button onClick={resume} disabled={loading}>续局</button>
          </div>
          <div className="divider" />
          <div className="fieldrow">
            <span>回放 ID</span>
            <input
              value={resumeId}
              onChange={(e) => setResumeId(e.target.value)}
              placeholder="粘贴 run_id，逐步播放整局"
              onKeyDown={(e) => e.key === 'Enter' && openReplay(resumeId)}
            />
            <button onClick={() => openReplay(resumeId)} disabled={loading || !resumeId}>🎬 整局回放</button>
          </div>
          {err && <div className="error">{err}</div>}
        </div>
        {cards.length > 0 && <DeckView mode="extras" />}
      </div>
    )
  }

  const hasReward = !view.reward_claimed && view.reward_options && view.reward_options.length > 0
  const hasForge = view.forge_available === true
  const hasEncounter = !view.in_battle && !!view.encounter
  const atShop = view.shop_available === true && view.shop
  const showShop = atShop && !shopDismissed
  const ended = view.status === 'won' || view.status === 'lost'

  return (
    <div className="screen">
      <header className="topbar">
        <span className="brand">卡牌闯关</span>
        {view.expedition && (
          <span className={`chip exp-chip ${view.expedition.status}`}>
            🚩 远征 第{view.expedition.chapter}/{view.expedition.chapters_total}章
            {view.expedition.status === 'won' && ' · 已通关'}
            {view.expedition.status === 'lost' && ' · 已终结'}
          </span>
        )}
        {view.coop && <CoopChip view={view} />}
        <span>生命 {view.health}/{view.max_health}</span>
        <span>金币 {view.gold}</span>
        <span>牌组 {view.deck.length}</span>
        <span className="sub">种子 {view.status === 'in_progress' && '#'}{view.seed === undefined ? '' : view.seed}</span>
        <button className="mini" onClick={refreshRun}>刷新</button>
        <button className="mini" onClick={() => openReplay(runId)} title="逐步播放、暂停、跳转整局（只读）">
          🎬 回放本局
        </button>
        {view.expedition && (
          <button className="mini" onClick={() => openExpeditionReplay()} title="逐章播放整段远征（只读）">
            🎬 整程回放
          </button>
        )}
        {inCoop && (
          <button className="mini" onClick={() => setCoopReplayId(coopPartyId || coopMe?.party_id)}
            title="队伍时间线、成员台账与逐章整程回放（只读）">
            🛡️ 队伍回放
          </button>
        )}
        <button className="mini" onClick={newRun}>新局</button>
      </header>

      {ended && (
        <div className="overlay">
          <div className="endcard">
            <h2>
              {view.status === 'won'
                ? (view.expedition
                  ? (view.expedition.status === 'won' ? '🏆 远征通关！' : '✅ 章节通关！')
                  : '🎉 通关！')
                : (view.expedition ? '💀 远征终结' : '💀 失败')}
            </h2>
            <p>
              {view.status === 'lost' && (view.expedition
                ? `远征在第 ${view.expedition.chapter} 章终结，已结算并更新解锁（新卡已解锁）；进行中的委托全部失败。`
                : '失败解锁了一张新卡。')}
              {view.status === 'won' && view.expedition && view.expedition.status === 'in_progress' &&
                `牌组、锻造成长与遗物将带入第 ${view.expedition.chapter + 1} 章。`}
              {view.status === 'won' && view.expedition && view.expedition.status === 'won' &&
                `已征服全部 ${view.expedition.chapters_total} 章，远征结算完成。`}
            </p>
            {view.status === 'won' && view.expedition?.status === 'in_progress' &&
              (view.commissions || []).some((q) => q.can_claim) && (
              <p className="comm-hint">📜 有委托已完成，可在进入下一章前先领取奖励（左侧委托面板）。</p>
            )}
            {view.status === 'won' && view.expedition?.status === 'in_progress' &&
              (view.commissions || []).filter((q) => q.can_claim).length > 0 && (
              <div className="endcomm">
                <p className="comm-hint">📜 有委托已完成，可在进入下一章前先领取奖励：</p>
                {view.commissions.filter((q) => q.can_claim).map((q) => (
                  <button key={q.id} className="primary comm-claim-end"
                          onClick={() => claimCommission(q.id)} disabled={loading}>
                    🎁 {q.kind === 'battle' ? '讨伐' : '贸易'}委托 · {q.reward.text}
                  </button>
                ))}
              </div>
            )}
            <DeckView />
            {inCoop && view.status === 'won' && view.expedition?.status === 'in_progress' && (
              <p className="comm-hint">
                🎁 本章队伍嘉奖已入共享金币池（累计 {view.coop.team_bonus}）；
                {coopMe?.role === 'leader' ? '作为队长，请带队进入下一章。' : '等待队长带队进入下一章（自动同步）…'}
              </p>
            )}
            <div className="fieldrow">
              {view.status === 'won' && view.expedition && view.expedition.status === 'in_progress' && (
                (!inCoop || coopMe?.role === 'leader') ? (
                  <button className="primary" onClick={advanceChapter} disabled={loading}>
                    {loading ? '开章中…' : `🚪 进入第 ${view.expedition.chapter + 1} 章`}
                  </button>
                ) : (
                  <span className="tag waiting">等待队长开章…</span>
                )
              )}
              {view.expedition && (
                <button onClick={() => openExpeditionReplay()}>🎬 整程回放</button>
              )}
              <button className="primary" onClick={newRun}>再来一局</button>
            </div>
          </div>
        </div>
      )}

      <div className="content">
        <div className="leftcol">
          <DeckView />
          {!view.in_battle && <PotionBelt />}
          <CoopRoster
            view={view}
            runId={runId}
            onSync={applyRun}
            onExpedition={(data) => {
              // 队长推进了章节：自动切到新章 run（其他队员的端上无缝续战）
              if (data.expedition.current_run_id !== runId) {
                applyRun(data.run)
                setRunId(data.run.run_id)
              }
            }}
          />
          <CompanionPanel />
          <CommissionPanel />
          <EncounterFlags />
          {view.unlocked_cards && <Unlocks unlocked={view.unlocked_cards} />}
        </div>
        <div className="maincol">
          {view.in_battle ? (
            <BattleView view={view} />
          ) : (
            <MapView view={view} />
          )}
          {atShop && shopDismissed && !ended && (
            <div className="shopreopen">
              <button className="primary" onClick={() => setShopDismissed(false)}>🛒 回到商店</button>
            </div>
          )}
          {hasReward && !ended && <RewardView view={view} />}
          {hasForge && !ended && <ForgeView view={view} />}
          {hasEncounter && !ended && <EncounterView view={view} />}
          {showShop && !ended && <ShopView view={view} onClose={() => setShopDismissed(true)} />}
        </div>
      </div>

      {replayId && (
        <ReplayPlayer runId={replayId} onClose={() => setReplayId(null)} />
      )}

      {expReplayId && (
        <ExpeditionReplay expeditionId={expReplayId} onClose={() => setExpReplayId(null)} />
      )}

      {coopReplayId && (
        <CoopReplay partyId={coopReplayId} onClose={() => setCoopReplayId(null)} />
      )}

      {err && <div className="error toast">{err}</div>}
    </div>
  )
}

function Unlocks({ unlocked }) {
  const { cardMeta } = useStore()
  return (
    <div className="panellist">
      <h3>已解锁卡</h3>
      <div className="unlockgrid">
        {unlocked.unlocked.map((id) => {
          const c = cardMeta(id)
          return <span key={id} className="chip">{c ? c.name : id}</span>
        })}
      </div>
    </div>
  )
}

function CoopChip({ view }) {
  const myId = JSON.parse(localStorage.getItem('cardrun.coop.me') || 'null')?.member_id
  const me = view.coop.members.find((m) => m.member_id === myId)
  return (
    <span className="chip coop-chip" title={`队伍 ${view.coop.member_count} 人 · 队伍嘉奖 ${view.coop.team_bonus}`}>
      🛡️ {me ? me.role_label : '协作'} · {view.coop.members.length}人 · 🎁{view.coop.team_bonus}
    </span>
  )
}