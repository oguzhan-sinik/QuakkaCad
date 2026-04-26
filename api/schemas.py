from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, List, Literal, Optional, Union
from uuid import UUID, uuid4



from pydantic import BaseModel, Field


class ObjectiveContent(BaseModel):
    block_type: Literal["objective"] = "objective"
    goal_statement: str = Field(description="The primary physical goal of the build")
    success_criteria: List[str] = Field(
        min_length=1,
        description="Bullet points defining when this component is 'done'",
    )


class VariableContent(BaseModel):
    block_type: Literal["variable"] = "variable"
    parameter_name: str = Field(description="e.g. 'Board Length', 'Battery Thickness'")
    value: float = Field(description="The numerical value agreed upon")
    unit: str = Field(description="Unit of measurement, e.g. 'mm', 'V', 'mAh'")
    is_locked: bool = Field(description="True only if the team explicitly agreed on this dimension")


class DecisionContent(BaseModel):
    block_type: Literal["decision"] = "decision"
    final_choice: str = Field(description="The agreed-upon approach")
    rejected_alternatives: List[str] = Field(
        default_factory=list,
        description="Ideas explicitly discarded by the team",
    )


class MissingInfoContent(BaseModel):
    block_type: Literal["missing_info"] = "missing_info"
    blocking_parameter: str = Field(description="The specific variable that is missing")
    impact: str = Field(description="What downstream process is halted because of this?")


AnyBlockContent = Annotated[
    Union[ObjectiveContent, VariableContent, DecisionContent, MissingInfoContent],
    Field(discriminator="block_type"),
]


class BlockStatus(str, Enum):
    DRAFTING = "drafting"
    LOCKED = "locked"
    REQUIRES_INPUT = "requires_input"


class PlanBlock(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    status: BlockStatus = Field(default=BlockStatus.DRAFTING)
    version: int = Field(default=1, description="Increments on every update to trigger UI renders")
    content: AnyBlockContent = Field(description="The structured payload for the Notion UI")
    reasoning: str = Field(min_length=10, description="Agent's justification for creating/updating this block")
    applied_lessons: List[str] = Field(default_factory=list, description="Lessons pulled from MuBit memory")


class TranscriptEntry(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    speaker_id: Optional[UUID] = Field(default=None)
    text: str = Field(min_length=1, description="The transcribed speech chunk")
    start_time: float = Field(ge=0.0, description="Seconds from start of audio stream")
    end_time: float = Field(ge=0.0, description="Seconds from start of audio stream")
    is_design_relevant: Optional[bool] = Field(default=None, description="True if about 3D design, False if off-topic, None if unclassified")


class ScriptEdit(BaseModel):
    """A search-and-replace edit to an OpenSCAD script."""
    search: str
    replace: str


class ModelDelta(BaseModel):
    """Records what changed between two model iterations — used by version control."""
    changed_block_ids: List[UUID]
    edits: List[ScriptEdit]
    is_full_regen: bool


class ModelIteration(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    script: str = Field(min_length=10, description="Raw code (OpenSCAD or CadQuery Python)")
    script_language: Literal["openscad", "cadquery"] = Field(default="openscad")
    reasoning: str = Field(description="Agent's justification for geometric decisions in this version")
    applied_lessons: List[str] = Field(default_factory=list, description="MuBit memory utilised")
    delta: Optional[ModelDelta] = Field(default=None, description="What changed from the previous iteration")
    compile_ok: Optional[bool] = Field(default=None, description="True if the final script compiled without errors")
    compile_stderr: Optional[str] = Field(default=None, description="Final OpenSCAD stderr after fix attempts")
    fix_iterations: int = Field(default=0, description="Number of LLM fix passes performed")


class Meeting(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    title: Optional[str] = None


class MeetingCreate(BaseModel):
    title: Optional[str] = None


class TranscriptEntryCreate(BaseModel):
    speaker_id: Optional[UUID] = None
    text: str = Field(min_length=1)
    start_time: float = Field(ge=0.0)
    end_time: float = Field(ge=0.0)


class PlanBlockCreate(BaseModel):
    status: BlockStatus = BlockStatus.DRAFTING
    version: int = 1
    content: AnyBlockContent
    reasoning: str = Field(min_length=10)
    applied_lessons: List[str] = Field(default_factory=list)


class ModelIterationCreate(BaseModel):
    script: str = Field(min_length=10)
    script_language: Literal["openscad", "cadquery"] = Field(default="openscad")
    reasoning: str
    applied_lessons: List[str] = Field(default_factory=list)


class FEAAnalysis(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_iteration_id: UUID = Field(description="Which model iteration was analysed")
    summary: str = Field(description="High-level summary of structural findings")
    stress_points: List[str] = Field(default_factory=list, description="Identified stress concentration areas")
    recommendations: List[str] = Field(default_factory=list, description="Design improvement suggestions")
    material_notes: str = Field(default="", description="Material-specific observations")
    safety_factor: Optional[float] = Field(default=None, description="Estimated safety factor if determinable")
    load_cases: List[str] = Field(default_factory=list, description="Load scenarios considered")
    full_report: str = Field(description="Detailed FEA-style analysis report in markdown")
    stress_script: str = Field(default="", description="OpenSCAD script with colour heat-map showing stress regions")


class TechnicalDrawing(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_iteration_id: UUID = Field(description="Which model iteration the drawing is for")
    image_url: str = Field(description="URL of the generated technical drawing image")
    prompt_used: str = Field(description="The prompt sent to the image model")


class MeetingState(BaseModel):
    meeting: Meeting
    transcript: List[TranscriptEntry]
    blocks: List[PlanBlock]
    models: List[ModelIteration]
