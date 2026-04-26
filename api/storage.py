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
        self.processed_counts: Dict[UUID, int] = {}  # meeting_id → last processed transcript entry index
        self.model_block_snapshots: Dict[UUID, set] = {}  # meeting_id → block IDs present at last model run
        self.stl_cache: Dict[UUID, bytes] = {}  # model_iteration_id → raw STL bytes

    def require_meeting(self, meeting_id: UUID) -> Meeting:
        m = self.meetings.get(meeting_id)
        if m is None:
            raise KeyError(meeting_id)
        return m


store = _Store()
