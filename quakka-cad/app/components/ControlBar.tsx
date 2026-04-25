interface ControlBarProps {
  isMuted: boolean;
  onToggleMute: () => void;
  onLeave: () => void;
}

export default function ControlBar({ isMuted, onToggleMute, onLeave }: ControlBarProps) {
  return (
    <div className="flex gap-3 pt-3 border-t border-zinc-700/50">
      <button
        onClick={onToggleMute}
        className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-colors ${
          isMuted
            ? "bg-red-500/20 text-red-400 hover:bg-red-500/30"
            : "bg-zinc-700 text-zinc-200 hover:bg-zinc-600"
        }`}
      >
        {isMuted ? "Unmute" : "Mute"}
      </button>
      <button
        onClick={onLeave}
        className="flex-1 py-2.5 rounded-lg text-sm font-medium bg-red-600 text-white hover:bg-red-700 transition-colors"
      >
        Leave
      </button>
    </div>
  );
}
