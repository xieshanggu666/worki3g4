import React, { useEffect, useState } from 'react'
import { api } from '../api'
import ExpeditionReplay from './ExpeditionReplay.jsx'

const KIND_ZH = {
  create: '组建队伍', join: '成员加入', role: '角色调整',
  leave: '成员离队', disband: '队伍解散', start: '开启远征',
  chapter_clear: '章节通关', advance: '进入下一章', settle: '远征结算',
}

// 协作队伍的整程回放：队伍事件时间线（组队/角色/开征/章节/结算）+ 最终贡献台账，
// 激活的远征可展开既有逐章整程回放（只读隔离）。
export default function CoopReplay({ partyId, onClose }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [showExp, setShowExp] = useState(false)

  useEffect(() => {
    let alive = true
    api.partyReplay(partyId)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(e.message))
    return () => { alive = false }
  }, [partyId])

  return (
    <div className="overlay" onClick={onClose}>
      <div className="endcard replay-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 900 }}>
        <h2>🛡️ 协作队伍整程回放</h2>
        {err && <div className="error">{err}</div>}
        {!data && !err && <p>加载中…</p>}
        {data && (
          <>
            <p className="sub">
              队伍状态：{data.party.status}
              {data.party.result && `（${data.party.result === 'won' ? '远征通关' : '远征失败'}）`}
              {data.isolated && ' · 全程只读，不写存档/不发解锁'}
            </p>
            <div className="coop-replay-events">
              {data.events.map((e) => (
                <div key={e.seq} className="ev-row">
                  <span className="sub">#{e.seq}</span>{' '}
                  <b>{KIND_ZH[e.kind] || e.kind}</b>{' '}
                  <EventDetail kind={e.kind} p={e.payload} />
                </div>
              ))}
            </div>
            {(() => {
              const settle = [...data.events].reverse()
                .find((e) => e.kind === 'settle')
              const ledger = settle?.payload?.ledger
              if (!ledger) return null
              return (
                <div>
                  <h3>结算台账 · 队伍嘉奖 {ledger.team_bonus} 金币</h3>
                  <div className="coop-ledger">
                    {ledger.members.map((m) => (
                      <div key={m.member_id} className="lrow">
                        <span>{m.name}（{m.role === 'leader' ? '队长'
                          : m.role === 'battle' ? '战斗位' : '资源位'}）</span>
                        <span className="sub">
                          战斗 {m.stats.battle_actions} · 路线 {m.stats.route_actions}
                          {' '}· 资源 {m.stats.supply_actions} · 胜场 {m.stats.battles_won}
                          {' '}· 花费 {m.stats.gold_spent} · <b>功勋 {m.stats.merit}</b>
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })()}
            {data.expedition && (
              <div className="fieldrow">
                <button className="primary" onClick={() => setShowExp(true)}>
                  🎬 打开远征整程回放（逐章可交互）
                </button>
              </div>
            )}
          </>
        )}
        <div className="fieldrow">
          <button className="primary" onClick={onClose}>关闭</button>
        </div>
      </div>
      {showExp && data?.party?.expedition_id && (
        <ExpeditionReplay expeditionId={data.party.expedition_id}
                         onClose={() => setShowExp(false)} />
      )}
    </div>
  )
}

function EventDetail({ kind, p }) {
  if (kind === 'create') return <span className="sub">队长 {p.leader_name} · 邀请码 {p.code}</span>
  if (kind === 'join') return <span className="sub">{p.name} 加入（{p.role === 'battle' ? '战斗位' : '资源位'}）</span>
  if (kind === 'role') return <span className="sub">{p.member} → {p.role === 'battle' ? '战斗位' : '资源位'}</span>
  if (kind === 'leave') return <span className="sub">{p.member} 离队</span>
  if (kind === 'disband') return <span className="sub">队长解散</span>
  if (kind === 'start') return <span className="sub">第 {p.chapters} 章远征开征</span>
  if (kind === 'advance') return <span className="sub">进入第 {p.chapter} 章</span>
  if (kind === 'chapter_clear') return <span className="sub">第 {p.chapter} 章通关 · 嘉奖累计 {p.team_bonus}</span>
  if (kind === 'settle') return <span className="sub">{p.result === 'won' ? '🏆 远征通关' : '💀 远征失败'}（第 {p.chapter} 章）</span>
  return null
}
