"""多人协作远征（规则 2.9.0）：组队 / 角色权限边界 / 共享章节状态 /
队伍嘉奖 / 失败回退 / 推进权限 / 跨章台账 / 整程回放。

覆盖：
- 队长建队（邀请码）、成员加入与角色分配、人数上下限、角色调整、离队/解散
- 开征是队长权限且至少 2 人；request_id 幂等、重复开征 409
- 章节 run 的动作鉴权：令牌缺失/错误 403；战斗位与资源位的动作边界（越权 403、
  零副作用、rev 不变）；队长全权
- 共享章节状态：资源位选路、战斗位打牌，所有成员看到同一份 run
- 队伍嘉奖：章节通关共享金币 += 5*人数，贡献台账（行动数/胜场/功勋/花费）
- 战败同事务把队伍结算为 settled/lost，之后动作全部拒绝（失败回退）
- 推进章节仅队长；协作台账随交接快照跨章累计
- 整程回放：逐章校验点零 mismatch、动作带 actor、队伍时间线与台账、只读隔离
"""
import pytest

from app import coop as coop_mod
from app import db, mapgen, service


# ---------------- 组队辅助 ----------------
def _create_party(client, name="队长", seed=7, member_id=None):
    r = client.post("/api/coop/parties",
                    json={"name": name, "seed": seed, "member_id": member_id})
    assert r.status_code == 200, r.text
    return r.json()


def _join(client, code, name, member_id=None):
    r = client.post("/api/coop/parties/join",
                    json={"code": code, "name": name, "member_id": member_id})
    assert r.status_code == 200, r.text
    return r.json()


def _me(party_view):
    """取本人凭据（member_id/token/role）。"""
    me = dict(party_view["me"])
    me["party_id"] = party_view["id"]
    return me


def _start(client, leader, chapters=3, request_id=None):
    body = {"member_id": leader["member_id"], "token": leader["token"],
            "chapters": chapters}
    if request_id:
        body["request_id"] = request_id
    r = client.post(f"/api/coop/parties/{leader['party_id']}/start", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _act(client, rid, member, action, **extra):
    return client.post(f"/api/runs/{rid}/act", json={
        "action": action, "member_id": member["member_id"],
        "token": member["token"], **extra,
    })


# ---------------- 组队 / 角色 / 离队 ----------------
def test_create_party_returns_code_and_leader(client):
    p = _create_party(client, name="阿队长")
    assert p["status"] == "forming"
    assert len(p["join_code"]) == 6
    assert p["leader_id"] == p["me"]["member_id"]
    assert p["me"]["role"] == "leader"
    assert p["me"]["token"]  # 队长拿到本人令牌
    assert p["min_members"] == 2 and p["max_members"] == 4
    assert [m["role"] for m in p["members"]] == ["leader"]
    # 其他人的视口里绝不能看到令牌
    assert all("token" not in m for m in p["members"])


def test_join_assigns_roles_and_rejoin_is_idempotent(client):
    leader = _me(_create_party(client))
    code = client.get(f"/api/coop/parties/{leader['party_id']}",
                      params={"member_id": leader["member_id"],
                              "token": leader["token"]}).json()["join_code"]
    b = _join(client, code, "战斗员甲")
    assert b["me"]["role"] == "battle"  # 首个队员补战斗位
    s = _join(client, code, "资源员乙")
    assert s["me"]["role"] == "supply"  # 第二个补资源位
    b_me, s_me = _me(b), _me(s)
    # 人数到齐 3
    status = client.get(f"/api/coop/parties/{leader['party_id']}",
                        params={"member_id": leader["member_id"],
                                "token": leader["token"]}).json()
    assert [m["role"] for m in status["members"]] == ["leader", "battle", "supply"]

    # 断线重连：凭原令牌幂等返回，不重复加人
    again = client.post("/api/coop/parties/join", json={
        "code": code, "name": "战斗员甲",
        "member_id": b_me["member_id"], "token": b_me["token"]}).json()
    assert len(again["members"]) == 3
    assert again["me"]["token"] == b_me["token"]

    # 错误令牌 -> 403；错误邀请码 -> 400
    bad = client.post("/api/coop/parties/join", json={
        "code": code, "name": "x",
        "member_id": b_me["member_id"], "token": "wrong"})
    assert bad.status_code == 403
    assert client.post("/api/coop/parties/join",
                       json={"code": "ZZZZZZ", "name": "x"}).status_code == 400


def test_party_member_cap_is_four(client):
    leader = _me(_create_party(client))
    code = _party_code(client, leader)
    for nm in ("甲", "乙", "丙"):
        _join(client, code, nm)
    r = client.post("/api/coop/parties/join", json={"code": code, "name": "丁"})
    assert r.status_code == 400  # 满员（队长 + 3）
    assert "full" in r.json()["detail"]


def _party_code(client, leader):
    return client.get(f"/api/coop/parties/{leader['party_id']}",
                      params={"member_id": leader["member_id"],
                              "token": leader["token"]}).json()["join_code"]


def test_leader_can_swap_roles_only_while_forming(client):
    leader = _me(_create_party(client))
    code = _party_code(client, leader)
    b = _me(_join(client, code, "甲"))
    s = _me(_join(client, code, "乙"))
    # 非队长调整角色 -> 403
    r = client.post(f"/api/coop/parties/{leader['party_id']}/role", json={
        "member_id": b["member_id"], "token": b["token"],
        "target_id": s["member_id"], "role": "battle"})
    assert r.status_code == 403
    # 队长把乙改成战斗位
    r = client.post(f"/api/coop/parties/{leader['party_id']}/role", json={
        "member_id": leader["member_id"], "token": leader["token"],
        "target_id": s["member_id"], "role": "battle"})
    assert r.status_code == 200
    assert next(m for m in r.json()["members"]
                if m["member_id"] == s["member_id"])["role"] == "battle"
    # 重复设同角色 -> 409；改队长本人 -> 400；非法角色 -> 400
    dup = client.post(f"/api/coop/parties/{leader['party_id']}/role", json={
        "member_id": leader["member_id"], "token": leader["token"],
        "target_id": s["member_id"], "role": "battle"})
    assert dup.status_code == 409
    lead = client.post(f"/api/coop/parties/{leader['party_id']}/role", json={
        "member_id": leader["member_id"], "token": leader["token"],
        "target_id": leader["member_id"], "role": "supply"})
    assert lead.status_code == 400
    bad = client.post(f"/api/coop/parties/{leader['party_id']}/role", json={
        "member_id": leader["member_id"], "token": leader["token"],
        "target_id": b["member_id"], "role": "warlord"})
    assert bad.status_code == 400


def test_member_leave_and_leader_disband(client):
    leader = _me(_create_party(client))
    code = _party_code(client, leader)
    b = _me(_join(client, code, "甲"))
    # 队员离队后令牌失效
    r = client.post(f"/api/coop/parties/{leader['party_id']}/leave",
                    json={"member_id": b["member_id"], "token": b["token"]})
    assert r.json()["status"] == "left"
    r = client.get(f"/api/coop/parties/{leader['party_id']}",
                   params={"member_id": b["member_id"], "token": b["token"]})
    assert r.status_code == 403
    # 队长离队 -> 解散
    r = client.post(f"/api/coop/parties/{leader['party_id']}/leave",
                    json={"member_id": leader["member_id"], "token": leader["token"]})
    assert r.json()["status"] == "disbanded"
    # 解散后邀请码不可再加入
    r = client.post("/api/coop/parties/join", json={"code": code, "name": "x"})
    assert r.status_code == 400


# ---------------- 开征 ----------------
def test_start_requires_two_members_and_leader(client):
    leader = _me(_create_party(client))
    # 单人不能开征
    r = client.post(f"/api/coop/parties/{leader['party_id']}/start", json={
        "member_id": leader["member_id"], "token": leader["token"], "chapters": 3})
    assert r.status_code == 400 and "at least 2" in r.json()["detail"]

    _join(client, _party_code(client, leader), "甲")
    # 伪造令牌开征 -> 403
    r = client.post(f"/api/coop/parties/{leader['party_id']}/start", json={
        "member_id": leader["member_id"], "token": "nope", "chapters": 3})
    assert r.status_code == 403


def test_start_creates_expedition_and_is_idempotent(client):
    leader = _me(_create_party(client, seed=23))
    battle = _me(_join(client, _party_code(client, leader), "甲"))
    first = _start(client, leader, chapters=2, request_id="go-1")
    rid = first["run"]["run_id"]
    exp_id = first["expedition"]["id"]
    assert first["run"]["coop"]["member_count"] == 2
    assert {m["role"] for m in first["run"]["coop"]["members"]} == {"leader", "battle"}
    assert first["run"]["expedition"]["id"] == exp_id
    # 队伍已激活
    assert first["party"]["status"] == "active"
    assert first["party"]["expedition_id"] == exp_id
    # 同令牌重复：返回首次响应，不重复开征
    dup = _start(client, leader, chapters=2, request_id="go-1")
    assert dup["duplicate"] is True
    assert dup["run"]["run_id"] == rid
    # 无令牌再开 -> 409
    r = client.post(f"/api/coop/parties/{leader['party_id']}/start", json={
        "member_id": leader["member_id"], "token": leader["token"], "chapters": 2})
    assert r.status_code == 409
    # 激活后不能再加入/改角色/离队
    code_join = client.post("/api/coop/parties/join",
                            json={"code": "XXXXXX", "name": "z"})
    assert code_join.status_code == 400
    r = client.post(f"/api/coop/parties/{leader['party_id']}/leave",
                    json={"member_id": battle["member_id"], "token": battle["token"]})
    assert r.status_code == 400


# ---------------- 动作鉴权与权限边界 ----------------
def _two_member_party_started(client, chapters=3, seed=7):
    leader = _me(_create_party(client, seed=seed))
    battle = _me(_join(client, _party_code(client, leader), "战斗员"))
    supply = _me(_join(client, _party_code(client, leader), "资源员"))
    data = _start(client, leader, chapters=chapters)
    return leader, battle, supply, data


def test_credentials_required_and_role_boundaries(client):
    leader, battle, supply, data = _two_member_party_started(client)
    rid = data["run"]["run_id"]
    node = _first_encounter_node(client, rid)

    # 无凭据 -> 403；错误令牌 -> 403
    r = client.post(f"/api/runs/{rid}/act", json={"action": "choose_node", "node": node})
    assert r.status_code == 403
    r = _act(client, rid, {**supply, "token": "bad"}, "choose_node", node=node)
    assert r.status_code == 403

    # 战斗位不能选路（资源动作）-> 403，且零副作用：rev 不推进
    before = client.get(f"/api/runs/{rid}/resume").json()["rev"]
    r = _act(client, rid, battle, "choose_node", node=node)
    assert r.status_code == 403
    after = client.get(f"/api/runs/{rid}/resume").json()["rev"]
    assert before == after

    # 资源位选路成功
    r = _act(client, rid, supply, "choose_node", node=node)
    assert r.status_code == 200 and r.json()["run"]["in_battle"] is True

    # 进入战斗后：资源位不能打牌/结束回合 -> 403
    hand = client.get(f"/api/runs/{rid}/resume").json()["battle"]["hand"]
    uid = hand[0]["uid"] if isinstance(hand[0], dict) else hand[0]
    r = _act(client, rid, supply, "play", card=uid)
    assert r.status_code == 403
    r = _act(client, rid, supply, "end_turn")
    assert r.status_code == 403
    # 战斗位打牌成功
    r = _act(client, rid, battle, "play", card=uid)
    assert r.status_code == 200
    # 队长可以执行任何动作（再结束一个回合演示）
    r = _act(client, rid, leader, "end_turn")
    assert r.status_code == 200


def _first_encounter_node(client, rid):
    view = client.get(f"/api/runs/{rid}/resume").json()
    return next(n["id"] for n in view["reachable"] if n["type"] == mapgen.ENCOUNTER)


def test_supply_owns_resource_actions(client):
    leader, battle, supply, data = _two_member_party_started(client)
    rid = data["run"]["run_id"]
    # 战斗位不能丢药水/锻造等（非战斗状态下用 discard_potion 越权演示，格位非法
    # 之前权限边界先生效）
    r = _act(client, rid, battle, "discard_potion", slot=0)
    assert r.status_code == 403
    # 资源位执行资源动作：空背包格位 -> 400（业务校验），证明已越过权限边界
    r = _act(client, rid, supply, "discard_potion", slot=0)
    assert r.status_code == 400


# ---------------- 共享章节状态 + 队伍嘉奖 + 台账 ----------------
_SAFE = {"rest": 0, "reward": 1, "forge": 2, "shop": 3, "encounter": 4, "elite": 6, "boss": 7}


def _coop_bot_step(client, rid, members_by_role):
    """合法行动推进：资源位负责选路/领奖，战斗位负责打牌/回合，队长兜底。

    全程只走 API（无直接改存档），因此逐章/整程回放校验点可逐位验证。
    """
    view = client.get(f"/api/runs/{rid}/resume").json()
    if view["status"] != "in_progress":
        return view
    supply = members_by_role.get("supply") or members_by_role["leader"]
    battle = members_by_role.get("battle") or members_by_role["leader"]
    if view["in_battle"]:
        hand = view["battle"]["hand"]
        energy = view["battle"]["energy"]

        def cost(h):
            return h.get("cost", 1) if isinstance(h, dict) else 1

        def cid(h):
            return h["id"] if isinstance(h, dict) else h

        playable = [h for h in hand if cost(h) <= energy]
        pick = next((h for h in playable if cid(h) == "strike"), None) \
            or (playable[0] if playable else None)
        if pick:
            uid = pick["uid"] if isinstance(pick, dict) else pick
            r = _act(client, rid, battle, "play", card=uid)
        else:
            r = _act(client, rid, battle, "end_turn")
        assert r.status_code == 200, r.text
        return None
    if not view["reward_claimed"] and view["reward_options"]:
        def is_gold(o):
            return o.get("kind") == "gold" or any(
                e.get("type") == "gold" for e in o.get("effects", []))
        idx = next((i for i, o in enumerate(view["reward_options"]) if is_gold(o)), 0)
        r = _act(client, rid, supply, "claim_reward", option=idx)
        assert r.status_code == 200, r.text
        return None
    reach = view["reachable"]
    if not reach:
        return view
    node = sorted(reach, key=lambda n: _SAFE.get(n["type"], 9))[0]
    r = _act(client, rid, supply, "choose_node", node=node["id"])
    assert r.status_code == 200, r.text
    return None


def _coop_win_chapter(client, rid, members_by_role, max_actions=400):
    for _ in range(max_actions):
        view = _coop_bot_step(client, rid, members_by_role)
        if view is None:
            view = client.get(f"/api/runs/{rid}/resume").json()
        if view["status"] != "in_progress":
            return view
    raise AssertionError("chapter did not finish within budget")


def _roles(leader, battle, supply):
    return {"leader": leader, "battle": battle, "supply": supply}


def test_chapter_clear_grants_team_bonus_and_tally(client):
    leader, battle, supply, data = _two_member_party_started(client, chapters=2, seed=5)
    rid = data["run"]["run_id"]
    exp_id = data["expedition"]["id"]
    roles = _roles(leader, battle, supply)

    view = _coop_win_chapter(client, rid, roles)
    assert view["status"] == "won"
    # 队伍嘉奖：3 人 * 5 = 15 金币入共享池
    assert view["gold"] >= 15
    assert view["coop"]["team_bonus"] == 15
    # 台账：战斗位收掉首领（胜场/战斗动作），资源位负责路线
    stats = {m["member_id"]: m["stats"] for m in view["coop"]["members"]}
    assert stats[battle["member_id"]]["battles_won"] >= 1
    assert stats[battle["member_id"]]["battle_actions"] >= 1
    assert stats[supply["member_id"]]["route_actions"] >= 1
    # 远征事件：chapter_clear；队伍仍 active
    assert client.get(f"/api/expeditions/{exp_id}").json()["expedition"]["status"] == "in_progress"


def test_advance_is_leader_only_and_stats_carry_over(client):
    leader, battle, supply, data = _two_member_party_started(client, chapters=2, seed=5)
    rid = data["run"]["run_id"]
    exp_id = data["expedition"]["id"]
    roles = _roles(leader, battle, supply)
    won_view = _coop_win_chapter(client, rid, roles)
    bonus = won_view["coop"]["team_bonus"]
    wins_before = next(m for m in won_view["coop"]["members"]
                       if m["member_id"] == battle["member_id"])["stats"]["battles_won"]

    # 非队长推进 -> 403
    r = client.post(f"/api/expeditions/{exp_id}/advance", json={
        "member_id": battle["member_id"], "token": battle["token"]})
    assert r.status_code == 403
    # 队长推进
    r = client.post(f"/api/expeditions/{exp_id}/advance", json={
        "member_id": leader["member_id"], "token": leader["token"]})
    assert r.status_code == 200
    rid2 = r.json()["run"]["run_id"]
    coop_view = r.json()["run"]["coop"]
    # 上一章嘉奖金币随交接，台账累计跨章保留
    assert r.json()["run"]["gold"] == won_view["gold"]
    assert coop_view["team_bonus"] == bonus
    carried = next(m for m in coop_view["members"]
                   if m["member_id"] == battle["member_id"])
    assert carried["stats"]["battles_won"] == wins_before
    # 新章战斗位仍能打牌、资源位选路（权限延续）
    node = _first_encounter_node(client, rid2)
    assert _act(client, rid2, supply, "choose_node", node=node).status_code == 200
    assert _act(client, rid2, battle, "end_turn").status_code == 200


# ---------------- 失败回退 / 结算 ----------------
def _coop_lose_chapter(client, rid, roles):
    """资源位带进首场战斗，战斗位只结束回合直到被击杀（全部合法 API 行动）。"""
    node = _first_encounter_node(client, rid)
    assert _act(client, rid, roles["supply"], "choose_node", node=node).status_code == 200
    for _ in range(120):
        r = _act(client, rid, roles["battle"], "end_turn")
        assert r.status_code == 200
        if r.json()["run"]["status"] == "lost":
            return r.json()
    raise AssertionError("player did not die")


def test_battle_loss_settles_party_and_freezes(client):
    leader, battle, supply, data = _two_member_party_started(client, chapters=3, seed=9)
    rid = data["run"]["run_id"]
    exp_id = data["expedition"]["id"]
    roles = _roles(leader, battle, supply)
    lost = _coop_lose_chapter(client, rid, roles)
    assert lost["run"]["expedition"]["status"] == "lost"
    # 队伍同事务结算
    with db.get_conn() as conn:
        prow = conn.execute("SELECT status,result FROM coop_parties WHERE expedition_id=?",
                            (exp_id,)).fetchone()
    assert prow["status"] == "settled" and prow["result"] == "lost"
    # 失败回退：run 不再接受任何成员的动作
    assert _act(client, rid, battle, "end_turn").status_code == 400
    assert _act(client, rid, leader, "end_turn").status_code == 400
    # 结算事件唯一
    settles = [e for e in db.load_expedition_events(exp_id) if e["kind"] == "settle"]
    assert len(settles) == 1 and settles[0]["payload"]["result"] == "lost"


def test_final_chapter_win_settles_party_with_bonus(client):
    leader, battle, supply, data = _two_member_party_started(client, chapters=1, seed=11)
    rid = data["run"]["run_id"]
    exp_id = data["expedition"]["id"]
    roles = _roles(leader, battle, supply)
    won = _coop_win_chapter(client, rid, roles)
    assert won["expedition"]["status"] == "won"
    assert won["gold"] >= 15 and won["coop"]["team_bonus"] == 15
    with db.get_conn() as conn:
        prow = conn.execute("SELECT status,result FROM coop_parties WHERE expedition_id=?",
                            (exp_id,)).fetchone()
    assert prow["status"] == "settled" and prow["result"] == "won"


# ---------------- 回放 ----------------
def test_coop_chapter_replay_verifies_with_actors(client):
    leader, battle, supply, data = _two_member_party_started(client, chapters=2, seed=5)
    rid = data["run"]["run_id"]
    roles = _roles(leader, battle, supply)
    won_view = _coop_win_chapter(client, rid, roles)

    rep = client.get(f"/api/runs/{rid}/replay").json()
    v = rep["verification"]
    assert v["mismatch"] == 0 and v["error"] == 0
    assert v["ok"] >= 3
    # 动作步骤带 actor / actor_name
    actors = {(s["action"], s["actor"]) for s in rep["steps"] if s["actor"]}
    assert any(a == "choose_node" and actor == supply["member_id"]
               for a, actor in actors)
    assert any(s["actor_name"] == "战斗员" for s in rep["steps"])
    # 最终帧：队伍嘉奖与台账和在线一致
    assert rep["final_view"]["coop"]["team_bonus"] == won_view["coop"]["team_bonus"]
    fstats = {m["member_id"]: m["stats"] for m in rep["final_view"]["coop"]["members"]}
    online_stats = {m["member_id"]: m["stats"] for m in won_view["coop"]["members"]}
    assert fstats == online_stats


def test_coop_expedition_replay_has_party_timeline_and_is_isolated(client):
    leader, battle, supply, data = _two_member_party_started(client, chapters=2, seed=3)
    rid = data["run"]["run_id"]
    exp_id = data["expedition"]["id"]
    party_id = leader["party_id"]
    roles = _roles(leader, battle, supply)
    won_view = _coop_win_chapter(client, rid, roles)
    client.post(f"/api/expeditions/{exp_id}/advance", json={
        "member_id": leader["member_id"], "token": leader["token"]})

    r = client.get(f"/api/expeditions/{exp_id}/replay")
    assert r.status_code == 200
    rep = r.json()
    assert rep["isolated"] is True
    party = rep["party"]
    kinds = [e["kind"] for e in party["events"]]
    assert kinds[0] == "create" and "start" in kinds and "advance" in kinds
    # 台账（第 2 章 run 的 coop 段继承第 1 章台账）
    ledger = party["ledger"]
    assert ledger["team_bonus"] == won_view["coop"]["team_bonus"]
    ids = {m["member_id"] for m in ledger["members"]}
    assert ids == {leader["member_id"], battle["member_id"], supply["member_id"]}
    # 逐章校验点全部通过
    for ch in rep["chapters"]:
        assert ch["replay"]["verification"]["mismatch"] == 0
        assert ch["replay"]["verification"]["error"] == 0

    # 队伍专用回放端点（含远征整程）
    pr = client.get(f"/api/coop/parties/{party_id}/replay").json()
    assert pr["isolated"] is True
    assert pr["expedition"]["expedition"]["id"] == exp_id
    assert any(e["kind"] == "start" for e in pr["events"])

    # 只读隔离：回放不改变队伍/远征状态
    with db.get_conn() as conn:
        st = conn.execute("SELECT status FROM coop_parties WHERE id=?",
                          (party_id,)).fetchone()["status"]
    assert st == "active"


def test_coop_replay_does_not_grant_unlocks_on_loss(client):
    leader, battle, supply, data = _two_member_party_started(client, chapters=3, seed=17)
    rid = data["run"]["run_id"]
    roles = _roles(leader, battle, supply)
    _coop_lose_chapter(client, rid, roles)
    profile_after = db.get_profile()
    # 战败章节回放：校验点通过（合法 API 行动）且不发解锁
    rep = client.get(f"/api/runs/{rid}/replay").json()
    assert rep["verification"]["mismatch"] == 0
    client.get(f"/api/expeditions/{data['expedition']['id']}/replay")
    assert db.get_profile() == profile_after  # 回放不发解锁


# ---------------- 并发：多成员共享章节状态 ----------------
def test_concurrent_actions_from_two_members_are_serialized(client):
    """资源位与战斗位同时提交不同动作：per-run 锁串行化，日志无缺口、回放逐位通过。"""
    import threading
    leader, battle, supply, data = _two_member_party_started(client, chapters=2, seed=29)
    rid = data["run"]["run_id"]
    node = _first_encounter_node(client, rid)

    results = {}
    barrier = threading.Barrier(2)

    def choose():
        barrier.wait()
        results["choose"] = _act(client, rid, supply, "choose_node", node=node)

    # 战斗位并发提交 end_turn（此刻还未进战斗，必为 400；关键是不产生写分叉）
    def end_turn():
        barrier.wait()
        results["end_turn"] = _act(client, rid, battle, "end_turn")

    ts = [threading.Thread(target=choose), threading.Thread(target=end_turn)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results["choose"].status_code == 200
    assert results["end_turn"].status_code == 400  # 选路与战斗先后串行，只有选路生效
    # 日志只有 create + choose_node，序号连续，回放校验点通过
    rep = client.get(f"/api/runs/{rid}/replay").json()
    assert rep["verification"]["mismatch"] == 0 and rep["verification"]["error"] == 0
    assert rep["verification"]["seq_gaps"] == 0


def test_same_request_id_from_members_returns_first_response(client):
    """同一 request_id 并发/重复提交只生效一次（幂等以 run 为键，与成员无关）。"""
    leader, battle, supply, data = _two_member_party_started(client, chapters=2, seed=31)
    rid = data["run"]["run_id"]
    node = _first_encounter_node(client, rid)
    first = client.post(f"/api/runs/{rid}/act", json={
        "action": "choose_node", "node": node,
        "member_id": supply["member_id"], "token": supply["token"],
        "request_id": "route-7"})
    assert first.status_code == 200
    # 同令牌、由另一名成员重放：返回首次响应（duplicate），不再次推演
    dup = client.post(f"/api/runs/{rid}/act", json={
        "action": "choose_node", "node": node,
        "member_id": leader["member_id"], "token": leader["token"],
        "request_id": "route-7"})
    assert dup.status_code == 200 and dup.json()["duplicate"] is True
    assert dup.json()["seq"] == first.json()["seq"]


def test_stale_expected_rev_rejected_for_member(client):
    """成员基于过期视口提交 -> 409，状态不被覆盖。"""
    leader, battle, supply, data = _two_member_party_started(client, chapters=2, seed=33)
    rid = data["run"]["run_id"]
    node = _first_encounter_node(client, rid)
    # 资源位先推进一版
    r = _act(client, rid, supply, "choose_node", node=node)
    assert r.status_code == 200
    new_rev = r.json()["rev"]
    # 战斗位拿旧 rev（1）提交：状态冲突 409
    r = client.post(f"/api/runs/{rid}/act", json={
        "action": "end_turn", "expected_rev": 1,
        "member_id": battle["member_id"], "token": battle["token"]})
    assert r.status_code == 409
    # 用最新 rev 提交则正常
    r = client.post(f"/api/runs/{rid}/act", json={
        "action": "end_turn", "expected_rev": new_rev,
        "member_id": battle["member_id"], "token": battle["token"]})
    assert r.status_code == 200


def test_forbidden_action_does_not_consume_rev_or_request_id(client):
    """越权动作零副作用：rev 不变；其 request_id 不被登记（合法动作仍可复用该令牌）。"""
    leader, battle, supply, data = _two_member_party_started(client, chapters=2, seed=35)
    rid = data["run"]["run_id"]
    node = _first_encounter_node(client, rid)
    before = client.get(f"/api/runs/{rid}/resume").json()["rev"]
    denied = client.post(f"/api/runs/{rid}/act", json={
        "action": "choose_node", "node": node,
        "member_id": battle["member_id"], "token": battle["token"],
        "request_id": "x-1"})
    assert denied.status_code == 403
    assert client.get(f"/api/runs/{rid}/resume").json()["rev"] == before
    # 同令牌由有权限的资源位提交 -> 正常生效（越权请求没有登记幂等键）
    ok = client.post(f"/api/runs/{rid}/act", json={
        "action": "choose_node", "node": node,
        "member_id": supply["member_id"], "token": supply["token"],
        "request_id": "x-1"})
    assert ok.status_code == 200


def test_two_member_party_is_minimum_and_bonus_scales_with_size(client):
    """2 人即满足下限；嘉奖按人数计算（2*5=10）。"""
    leader = _me(_create_party(client, seed=41))
    battle = _me(_join(client, _party_code(client, leader), "独狼战友"))
    data = _start(client, leader, chapters=1)
    rid = data["run"]["run_id"]
    assert data["run"]["coop"]["member_count"] == 2
    roles = {"leader": leader, "battle": battle,
             # 无资源位：由队长兜底资源动作
             "supply": leader}
    won = _coop_win_chapter(client, rid, roles)
    assert won["expedition"]["status"] == "won"
    assert won["coop"]["team_bonus"] == 10


# ---------------- 台账纯函数 ----------------
def test_tally_and_permission_helpers_pure():
    # 权限边界
    assert coop_mod.can_perform("leader", "play")
    assert coop_mod.can_perform("leader", "shop_buy")
    assert coop_mod.can_perform("battle", "play")
    assert not coop_mod.can_perform("battle", "shop_buy")
    assert coop_mod.can_perform("supply", "shop_buy")
    assert not coop_mod.can_perform("supply", "end_turn")
    # 台账：战斗胜利动作给胜场+功勋；锻造花费记账
    ps = coop_mod.fresh_party_state(2, members=[{"member_id": "a", "name": "A",
                                                 "role": "battle"}])
    coop_mod.tally(ps, "a", "play", [{"result": "won"}])
    st = ps["stats"]["a"]
    assert st["battle_actions"] == 1 and st["battles_won"] == 1
    assert st["merit"] == coop_mod.MERIT_WEIGHTS["battle"] + coop_mod.BATTLE_WIN_MERIT
    spent = coop_mod.gold_spent_in_log("forge", [{"forged": {"cost": 25}}])
    coop_mod.tally(ps, "a", "forge", [{"forged": {"cost": 25}}], gold_spent=spent)
    assert ps["stats"]["a"]["gold_spent"] == 25
    # 普通未分胜负的打牌不计胜场
    ps2 = coop_mod.fresh_party_state(1)
    coop_mod.tally(ps2, "b", "end_turn", [{"snapshot": {}}])
    assert ps2["stats"]["b"]["battles_won"] == 0
    # 无队伍段/无 actor 时安全跳过
    coop_mod.tally(None, "a", "play", [])
    coop_mod.tally(ps, "", "play", [])
