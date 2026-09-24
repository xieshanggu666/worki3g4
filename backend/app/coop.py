"""多人协作远征（规则 2.9.0）：队伍身份、权限边界、贡献台账的纯逻辑。

- 队长（leader）：组队/角色分配/开征/推进章节，并可执行任何行动；
- 战斗位（battle）：打牌、结束回合、战斗中使用药水；
- 资源位（supply）：路线选择、领奖、锻造、商店、药水整理、委托、伙伴、奇遇抉择。
行动鉴权是服务端权威的：越权动作在事务内被拒（403），零副作用。

贡献台账（coop.stats）是动作序列的确定性函数——在线行动与回放重建共用
``tally`` 同一条推演路径，因此整程回放无需读队伍表即可逐位复算每章台账。
"""
from __future__ import annotations

LEADER = "leader"
BATTLE = "battle"
SUPPLY = "supply"
ROLES = (LEADER, BATTLE, SUPPLY)

# 组队阶段
FORMING = "forming"
ACTIVE = "active"
SETTLED = "settled"
DISBANDED = "disbanded"

MIN_MEMBERS = 2
MAX_MEMBERS = 4

# 行动 -> 权限类别：
# - battle：战斗位（与队长）可执行；
# - supply：资源位（与队长）可执行。
# choose_node 归资源位（路线决策）；commission_claim 同（战后领奖）。
BATTLE_ACTIONS = frozenset({"play", "end_turn", "use_potion"})
SUPPLY_ACTIONS = frozenset({
    "choose_node", "claim_reward", "forge", "shop_buy", "shop_remove",
    "discard_potion", "companion_set_mode", "commission_accept",
    "commission_claim", "encounter_choice",
})

# 各类行动的功勋权重（成功执行一次）
MERIT_WEIGHTS = {
    "battle": 3,    # 打牌/回合/战斗药水：一线操作
    "supply": 1,    # 领奖/锻造/交易/整理等资源操作
    "route": 2,     # 路线选择决定远征走向
}

# 队伍金币嘉奖：每通关一章，每名队员 CHAPTER_BONUS_PER_MEMBER 金币（共享牌组金币池）
CHAPTER_BONUS_PER_MEMBER = 5
BATTLE_WIN_MERIT = 5      # 赢得一场战斗的额外功勋（给该动作的执行者）


class CoopAuthError(Exception):
    """队伍鉴权失败：令牌错误/成员已离队/非本队（HTTP 403）。"""
    pass


class CoopPermissionError(CoopAuthError):
    """越权操作：成员角色不允许该行动（HTTP 403；是鉴权失败的一种）。"""
    pass


def can_perform(role, action):
    """角色是否可以执行该行动。队长全权；战斗/资源位各守边界。"""
    if role == LEADER:
        return True
    if role == BATTLE:
        return action in BATTLE_ACTIONS
    if role == SUPPLY:
        return action in SUPPLY_ACTIONS
    return False


def fresh_stats():
    """新的一章/新队伍的贡献台账。"""
    return {
        "battle_actions": 0,   # 打牌/结束回合/战斗药水次数
        "supply_actions": 0,   # 领奖/锻造/商店/委托/奇遇等次数
        "route_actions": 0,    # choose_node 次数
        "battles_won": 0,      # 本人动作收掉的战斗胜场
        "gold_spent": 0,       # 本人在锻造/商店中花掉的金币
        "merit": 0,            # 综合功勋
    }


def fresh_party_state(member_count, chapter=1, members=None):
    """run 状态里的 coop 段：成员名册 + 各成员台账 + 队伍嘉奖累计（随章节快照继承）。

    members 为 [{member_id,name,role}] 名册（仅公开信息、无令牌），供视口与
    回放重建直接呈现；整程远征中名册不变，随交接快照跨章携带。
    """
    return {
        "member_count": member_count,
        "chapter": chapter,
        "members": list(members or []),
        "stats": {},          # member_id -> fresh_stats()
        "team_bonus": 0,      # 截至目前队伍嘉奖金币总额
    }


def chapter_bonus(member_count):
    """本章通关的队伍金币嘉奖（共享金币池）。"""
    return CHAPTER_BONUS_PER_MEMBER * max(0, member_count)


def _ensure_member(party_state, actor):
    stats = party_state.setdefault("stats", {})
    if actor not in stats:
        # 回放/旧快照容错：未在册的 actor 也照常记账（不阻断回放）
        stats[actor] = fresh_stats()
    return stats[actor]


def tally(party_state, actor, action, log=None, gold_spent=0):
    """一个成功动作后的贡献台账推演（纯函数；在线与回放共用）。

    成功判定在调用方（权限校验/动作推演通过后才调用）。gold_spent 由调用方
    从该步日志中确定性提取（锻造/商店交易记录），避免与金币的其它来源混淆。
    """
    if not party_state or not actor:
        return
    st = _ensure_member(party_state, actor)
    if action in BATTLE_ACTIONS:
        st["battle_actions"] += 1
        st["merit"] += MERIT_WEIGHTS["battle"]
    elif action == "choose_node":
        st["route_actions"] += 1
        st["merit"] += MERIT_WEIGHTS["route"]
    elif action in SUPPLY_ACTIONS:
        st["supply_actions"] += 1
        st["merit"] += MERIT_WEIGHTS["supply"]
    if gold_spent:
        st["gold_spent"] += gold_spent
    # 该动作是否收掉一场战斗（普通战/伏击战胜利）
    if action in BATTLE_ACTIONS and _step_won(log):
        st["battles_won"] += 1
        st["merit"] += BATTLE_WIN_MERIT


def _step_won(log):
    if not log:
        return False
    for ev in log:
        if isinstance(ev, dict) and ev.get("result") in ("won", "run_won"):
            return True
        if isinstance(ev, dict) and (ev.get("encounter_ambush_result") or {}).get("won"):
            return True
    return False


def gold_spent_in_log(action, log):
    """从动作日志确定性提取本步花费（锻造/商店购买/移除）。"""
    if action == "forge":
        for ev in log or []:
            f = ev.get("forged") if isinstance(ev, dict) else None
            if f and f.get("cost"):
                return f["cost"]
    if action in ("shop_buy", "shop_remove"):
        for ev in log or []:
            tx = ev.get("shop_tx") if isinstance(ev, dict) else None
            if tx and tx.get("price"):
                return tx["price"]
    return 0


def grant_chapter_bonus(run_party_state, member_count, log, chapter, chapters_total):
    """章节通关的队伍嘉奖（纯推演）：共享金币池 += 5*人数。

    非终章每章通关发；终章通关（远征 won）同样发一份「征服嘉奖」。
    返回 (嘉奖金额, 事件)；幂等由调用方的章节通关一次性保证。
    """
    amount = chapter_bonus(member_count)
    run_party_state["team_bonus"] = run_party_state.get("team_bonus", 0) + amount
    ev = {"team_bonus": {
        "amount": amount, "members": member_count,
        "chapter": chapter, "chapters_total": chapters_total,
    }}
    if log is not None:
        log.append(ev)
    return amount, ev


# ---------- 只读视口 ----------
def role_label(role):
    return {LEADER: "队长", BATTLE: "战斗位", SUPPLY: "资源位"}.get(role, role)


def member_public(member, stats=None):
    out = {
        "member_id": member["member_id"],
        "name": member["name"],
        "role": member["role"],
        "role_label": role_label(member["role"]),
        "seq": member.get("seq"),
    }
    if stats is not None:
        out["stats"] = stats
    return out


def party_view(party, members, run_party_state=None):
    """队伍公开视口（绝不包含 token）。"""
    stats_map = (run_party_state or {}).get("stats") if run_party_state else None
    return {
        "id": party["id"],
        "join_code": party["join_code"] if party["status"] == FORMING else None,
        "status": party["status"],
        "result": party.get("result"),
        "leader_id": party["leader_id"],
        "expedition_id": party.get("expedition_id"),
        "rev": party["rev"],
        "min_members": MIN_MEMBERS,
        "max_members": MAX_MEMBERS,
        "members": [
            member_public(m, (stats_map or {}).get(m["member_id"]))
            for m in members if not m.get("left")
        ],
        "team_bonus": (run_party_state or {}).get("team_bonus", 0)
                      if run_party_state else 0,
    }
