from fastapi import APIRouter, HTTPException

from .. import service
from .. import coop as coop_mod
from ..schemas import (
    CreatePartyRequest, JoinPartyRequest, PartyRejoinRequest,
    PartyRoleRequest, PartyLeaveRequest, StartPartyRequest,
)

router = APIRouter(prefix="/api/coop", tags=["coop"])


@router.post("/parties")
def create_party(body: CreatePartyRequest):
    try:
        return service.create_party(body.name, seed=body.seed, member_id=body.member_id)
    except service.InvalidAction as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/parties/join")
def join_party(body: JoinPartyRequest):
    try:
        return service.join_party(body.code, body.name, member_id=body.member_id,
                                  token=body.token)
    except coop_mod.CoopAuthError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except service.InvalidAction as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/parties/{party_id}")
def party_status(party_id: str, member_id: str, token: str):
    try:
        return service.party_status(party_id, member_id, token)
    except coop_mod.CoopAuthError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except service.InvalidAction as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/parties/{party_id}/role")
def change_role(party_id: str, body: PartyRoleRequest):
    try:
        return service.change_member_role(party_id, body.member_id, body.token,
                                          body.target_id, body.role)
    except coop_mod.CoopAuthError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except service.DuplicateReward as e:
        raise HTTPException(status_code=409, detail=str(e))
    except service.InvalidAction as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/parties/{party_id}/leave")
def leave_party(party_id: str, body: PartyLeaveRequest):
    try:
        return service.leave_party(party_id, body.member_id, body.token)
    except coop_mod.CoopAuthError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except service.InvalidAction as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/parties/{party_id}/start")
def start_party_expedition(party_id: str, body: StartPartyRequest):
    try:
        return service.start_party(party_id, body.member_id, body.token,
                                   chapters=body.chapters, request_id=body.request_id)
    except coop_mod.CoopAuthError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except service.DuplicateReward as e:
        raise HTTPException(status_code=409, detail=str(e))
    except service.InvalidAction as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/parties/{party_id}/replay")
def party_replay(party_id: str):
    try:
        return service.party_replay(party_id)
    except service.InvalidAction as e:
        raise HTTPException(status_code=400, detail=str(e))
