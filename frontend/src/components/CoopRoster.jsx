import { useEffect, useRef } from 'react'
import { api } from '../api'

// 远征中的队伍侧栏：
// - 每 2 秒轻量轮询 /resume 同步其他队员推进的章节状态（位置/战斗/金币/嘉奖）；
// - 展示成员名册与各角色、本人身份、贡献台账与队伍金币嘉奖。
// 纯展示 + 同步：动作仍由地图/战斗/商店等面板提交（服务端按角色鉴权，越权 403）。
export default function CoopRoster({ view, runId, onSync, onExpedition }) {
  const timer = useRef(null)
  const revRef = useRef(view?.rev)
  revRef.current = view?.rev

  useEffect(() => {
    if (!view?.coop) return
    timer.current = setInterval(async () => {
      try {
        // 章节通关等待队长推进：当前 run 已结束时轮询远征视口——队长开新章后
        // current_run_id 变化，回调上层切到新章 run；进行中则比对 run 的 rev。
        if (view.status !== 'in_progress' && view.expedition?.id) {
          const exp = await api.getExpedition(view.expedition.id)
          onExpedition?.(exp)
          return
        }
        const fresh = await api.resume(runId)
        if (Number.isInteger(fresh.rev) && fresh.rev !== revRef.current) {
          onSync?.(fresh)
        }
      } catch (_) { /* 轮询失败静默，下个周期重试 */ }
    }, 2000)
    return () => clearInterval(timer.current)
  }, [view?.coop != null, runId, view?.status, onSync, onExpedition])

  if (!view?.coop) return null
  const coop = view.coop
  const myId = JSON.parse(localStorage.getItem('cardrun.coop.me') || 'null')?.member_id
  const myRole = coop.members.find((m) => m.member_id === myId)?.role

  return (
    <div className="panellist coop-roster">
      <h3>🛡️ 协作队伍</h3>
      <div className="coop-myrole">
        我的角色：<b>{coop.members.find((m) => m.member_id === myId)?.role_label || '观战'}</b>
        {myRole === 'battle' && <span className="sub">（打牌 / 结束回合 / 战斗药水）</span>}
        {myRole === 'supply' && <span className="sub">（选路 / 领奖 / 锻造 / 商店）</span>}
        {myRole === 'leader' && <span className="sub">（全权 · 推进章节）</span>}
      </div>
      <ul className="coop-stats">
        {coop.members.map((m) => {
          const s = m.stats || {}
          return (
            <li key={m.member_id} className={`role-${m.role}`}>
              <div className="coop-stat-head">
                <span>{m.name}{m.member_id === myId && '（我）'}</span>
                <span className={`chip role-chip ${m.role}`}>{m.role_label}</span>
              </div>
              <div className="coop-stat-row">
                <span>战斗 {s.battle_actions || 0}</span>
                <span>路线 {s.route_actions || 0}</span>
                <span>资源 {s.supply_actions || 0}</span>
              </div>
              <div className="coop-stat-row">
                <span>胜场 {s.battles_won || 0}</span>
                <span>功勋 {s.merit || 0}</span>
                <span>花费 {s.gold_spent || 0}</span>
              </div>
            </li>
          )
        })}
      </ul>
      <div className="coop-bonus">🎁 队伍嘉奖累计：{coop.team_bonus} 金币（共享池）</div>
    </div>
  )
}
