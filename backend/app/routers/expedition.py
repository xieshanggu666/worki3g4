from fastapi import APIRouter, HTTPException

from .. import service
from .. import coop as coop_mod
from ..schemas import AdvanceRequest, CreateExpeditionRequest

router = APIRouter(prefix="/api/expeditions", tags=["expedition"])


@router.post("")
def create_expedition(body: CreateExpeditionRequest):
    try:
        return service.create_expedition(seed=body.seed, chapters=body.chapters)
    except service.InvalidAction as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{exp_id}")
def get_expedition(exp_id: str):
    try:
        return service.get_expedition(exp_id)
    except service.InvalidAction as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{exp_id}/advance")
def advance(exp_id: str, body: AdvanceRequest):
    try:
        return service.advance_expedition(
            exp_id, request_id=body.request_id,
            member_id=body.member_id, token=body.token)
    except (coop_mod.CoopAuthError, coop_mod.CoopPermissionError) as e:
        # 协作远征：令牌错误/非队长推进 -> 403，零副作用
        raise HTTPException(status_code=403, detail=str(e))
    except service.DuplicateReward as e:
        # 远征已结算：不重复结算、不再开章
        raise HTTPException(status_code=409, detail=str(e))
    except service.StaleState as e:
        # 状态冲突：远征记录被并发推进，请刷新重试
        raise HTTPException(status_code=409, detail=str(e))
    except service.InvalidAction as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{exp_id}/replay")
def expedition_replay(exp_id: str):
    try:
        return service.expedition_replay(exp_id)
    except service.InvalidAction as e:
        raise HTTPException(status_code=400, detail=str(e))
