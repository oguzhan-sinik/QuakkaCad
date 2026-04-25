from typing import Dict, List
from uuid import UUID

from schemas import Meeting, ModelIteration, PlanBlock, TranscriptEntry


class _Store:
    def __init__(self) -> None:
        self.meetings: Dict[UUID, Meeting] = {}
        self.transcripts: Dict[UUID, List[TranscriptEntry]] = {}
        self.blocks: Dict[UUID, List[PlanBlock]] = {}
        self.block_index: Dict[UUID, UUID] = {}  # block_id -> meeting_id
        self.models: Dict[UUID, List[ModelIteration]] = {}

    def require_meeting(self, meeting_id: UUID) -> Meeting:
        m = self.meetings.get(meeting_id)
        if m is None:
            raise KeyError(meeting_id)
        return m


store = _Store()
