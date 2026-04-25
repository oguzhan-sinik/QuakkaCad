"use client";

// --------------------------------------------------------------------------
// Types (mirror api/schemas.py)
// --------------------------------------------------------------------------

export type BlockStatus = "drafting" | "locked" | "requires_input";

export interface ObjectiveContent {
  block_type: "objective";
  goal_statement: string;
  success_criteria: string[];
}

export interface VariableContent {
  block_type: "variable";
  parameter_name: string;
  value: number;
  unit: string;
  is_locked: boolean;
}

export interface DecisionContent {
  block_type: "decision";
  final_choice: string;
  rejected_alternatives: string[];
}

export interface MissingInfoContent {
  block_type: "missing_info";
  blocking_parameter: string;
  impact: string;
}

export type AnyBlockContent =
  | ObjectiveContent
  | VariableContent
  | DecisionContent
  | MissingInfoContent;

export interface PlanBlock {
  id: string;
  status: BlockStatus;
  version: number;
  content: AnyBlockContent;
  reasoning: string;
  applied_lessons: string[];
}

// --------------------------------------------------------------------------
// Rainbow border
// --------------------------------------------------------------------------

// Each block gets a phase offset so they don't all share the same leading colour.
const RAINBOW = "conic-gradient(from 0deg, #ff0000, #ff8800, #ffff00, #00ff88, #00ccff, #8844ff, #ff00cc, #ff0000)";

function RainbowBorder({ children, index }: { children: React.ReactNode; index: number }) {
  return (
    <div className="relative rounded-lg p-[2px] overflow-hidden">
      {/* Spinning gradient — oversized so corners stay covered while rotating */}
      <div
        className="absolute inset-[-100%]"
        style={{
          background: RAINBOW,
          animation: "rainbow-spin 1.8s linear infinite",
          animationDelay: `${-(index * 0.26)}s`,
        }}
      />
      <div className="relative">{children}</div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Sub-components
// --------------------------------------------------------------------------

function StatusChip({ status }: { status: BlockStatus }) {
  const styles: Record<BlockStatus, string> = {
    drafting: "bg-zinc-700 text-zinc-400",
    locked: "bg-emerald-900/60 text-emerald-400",
    requires_input: "bg-amber-900/60 text-amber-400",
  };
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${styles[status]}`}>
      {status.replace("_", " ")}
    </span>
  );
}

function BlockHeader({ label, status, version }: { label: string; status: BlockStatus; version: number }) {
  return (
    <div className="flex items-center justify-between mb-2">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
        {label}
      </span>
      <div className="flex items-center gap-1.5">
        {version > 1 && <span className="text-[10px] text-zinc-600">v{version}</span>}
        <StatusChip status={status} />
      </div>
    </div>
  );
}

function ObjectiveBlock({
  block,
  loading,
}: {
  block: PlanBlock & { content: ObjectiveContent };
  loading: boolean;
}) {
  return (
    <div className={`bg-indigo-950/40 rounded-lg p-3 ${loading ? "" : "border border-indigo-800/40"}`}>
      <BlockHeader label="Objective" status={block.status} version={block.version} />
      <p className="text-sm font-medium text-zinc-200 leading-snug">
        {block.content.goal_statement}
      </p>
      {block.content.success_criteria.length > 0 && (
        <ul className="mt-2 space-y-1">
          {block.content.success_criteria.map((criterion, i) => (
            <li key={i} className="flex gap-2 text-xs text-zinc-400">
              <span className="text-indigo-500 flex-shrink-0 mt-0.5">✓</span>
              <span>{criterion}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function VariableBlock({
  block,
  loading,
}: {
  block: PlanBlock & { content: VariableContent };
  loading: boolean;
}) {
  const { parameter_name, value, unit, is_locked } = block.content;
  return (
    <div className={`bg-zinc-800/60 rounded-lg p-3 ${loading ? "" : "border border-zinc-700/50"}`}>
      <BlockHeader label="Variable" status={block.status} version={block.version} />
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm text-zinc-300 truncate">{parameter_name}</span>
        <div className="flex items-baseline gap-1 flex-shrink-0">
          {is_locked && (
            <span className="text-[10px] text-emerald-500 mr-1" title="Team-agreed value">
              ⬛
            </span>
          )}
          <span className="text-sm font-mono font-semibold text-zinc-100">{value}</span>
          <span className="text-xs text-zinc-500">{unit}</span>
        </div>
      </div>
    </div>
  );
}

function DecisionBlock({
  block,
  loading,
}: {
  block: PlanBlock & { content: DecisionContent };
  loading: boolean;
}) {
  const { final_choice, rejected_alternatives } = block.content;
  return (
    <div className={`bg-zinc-800/60 rounded-lg p-3 ${loading ? "" : "border border-zinc-700/50"}`}>
      <BlockHeader label="Decision" status={block.status} version={block.version} />
      <p className="text-sm text-zinc-200">{final_choice}</p>
      {rejected_alternatives.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {rejected_alternatives.map((alt, i) => (
            <li key={i} className="text-xs text-zinc-600 line-through">
              {alt}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MissingInfoBlock({
  block,
  loading,
}: {
  block: PlanBlock & { content: MissingInfoContent };
  loading: boolean;
}) {
  const { blocking_parameter, impact } = block.content;
  return (
    <div className={`bg-amber-950/30 rounded-lg p-3 ${loading ? "" : "border border-amber-800/40"}`}>
      <BlockHeader label="Missing Info" status={block.status} version={block.version} />
      <p className="text-sm font-medium text-amber-300">{blocking_parameter}</p>
      <p className="text-xs text-zinc-500 mt-1 leading-snug">{impact}</p>
    </div>
  );
}

function Block({ block, isTargeted, index }: { block: PlanBlock; isTargeted: boolean; index: number }) {
  const inner = (() => {
    switch (block.content.block_type) {
      case "objective":
        return <ObjectiveBlock block={block as PlanBlock & { content: ObjectiveContent }} loading={isTargeted} />;
      case "variable":
        return <VariableBlock block={block as PlanBlock & { content: VariableContent }} loading={isTargeted} />;
      case "decision":
        return <DecisionBlock block={block as PlanBlock & { content: DecisionContent }} loading={isTargeted} />;
      case "missing_info":
        return <MissingInfoBlock block={block as PlanBlock & { content: MissingInfoContent }} loading={isTargeted} />;
    }
  })();

  if (!isTargeted) return inner;

  return (
    <RainbowBorder index={index}>{inner}</RainbowBorder>
  );
}

// --------------------------------------------------------------------------
// Main component
// --------------------------------------------------------------------------

interface PlanSidebarProps {
  blocks: PlanBlock[];
  isLoading?: boolean;
  targetedBlockIds?: Set<string>;
  onRunPlanner?: () => void;
}

export default function PlanSidebar({ blocks, isLoading = false, targetedBlockIds, onRunPlanner }: PlanSidebarProps) {
  const objectiveCount = blocks.filter((b) => b.content.block_type === "objective").length;
  const variableCount = blocks.filter((b) => b.content.block_type === "variable").length;
  const missingCount = blocks.filter((b) => b.content.block_type === "missing_info").length;

  return (
    <div className="h-full flex-1 flex flex-col bg-zinc-900 rounded-xl border border-zinc-700/50 min-h-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700/50 flex-shrink-0">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">Plan</h3>
          {isLoading && (
            <svg className="animate-spin h-3 w-3 text-indigo-400" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
          )}
          {blocks.length > 0 && (
            <span className="text-[10px] text-zinc-600">{blocks.length} blocks</span>
          )}
        </div>
        <button
          onClick={onRunPlanner}
          disabled={isLoading || !onRunPlanner}
          className="text-xs px-2.5 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-500 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isLoading ? "Running..." : "Run Planner"}
        </button>
      </div>

      {/* Stats strip — only when there are blocks */}
      {blocks.length > 0 && (
        <div className="flex gap-3 px-4 py-2 border-b border-zinc-800 flex-shrink-0">
          <span className="text-[10px] text-zinc-500">
            <span className="text-indigo-400 font-medium">{objectiveCount}</span> objective
          </span>
          <span className="text-[10px] text-zinc-500">
            <span className="text-zinc-300 font-medium">{variableCount}</span> variable{variableCount !== 1 ? "s" : ""}
          </span>
          {missingCount > 0 && (
            <span className="text-[10px] text-zinc-500">
              <span className="text-amber-400 font-medium">{missingCount}</span> missing
            </span>
          )}
        </div>
      )}

      {/* Block list */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2 min-h-0">
        {blocks.length === 0 && !isLoading && (
          <p className="text-zinc-600 text-sm text-center mt-8 px-4">
            Plan blocks will appear here after the planner runs...
          </p>
        )}

        {isLoading && blocks.length === 0 && (
          <p className="text-zinc-500 text-sm text-center mt-8 animate-pulse">
            Analysing transcript...
          </p>
        )}

        {blocks.map((block, i) => (
          <Block
            key={block.id}
            block={block}
            isTargeted={targetedBlockIds?.has(block.id) ?? false}
            index={i}
          />
        ))}
      </div>
    </div>
  );
}
