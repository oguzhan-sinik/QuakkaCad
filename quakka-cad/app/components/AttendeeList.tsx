import type { Peer } from "../lib/useConference";

interface AttendeeListProps {
  peers: Peer[];
  myName: string;
  isMuted: boolean;
}

export default function AttendeeList({ peers, myName, isMuted }: AttendeeListProps) {
  return (
    <div className="max-h-40 min-h-0 overflow-y-auto">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-3">
        Attendees ({peers.length + 1})
      </h3>
      <ul className="space-y-1">
        <li className="flex items-center justify-between px-3 py-2 rounded-lg bg-zinc-800/50">
          <span className="text-sm font-medium truncate">
            {myName} <span className="text-zinc-500">(you)</span>
          </span>
          {isMuted && (
            <span className="text-red-400 text-xs flex-shrink-0 ml-2">MIC OFF</span>
          )}
        </li>
        {peers.map((peer) => (
          <li
            key={peer.peerId}
            className="flex items-center justify-between px-3 py-2 rounded-lg bg-zinc-800/50"
          >
            <span className="text-sm font-medium truncate">{peer.name}</span>
            {peer.muted && (
              <span className="text-red-400 text-xs flex-shrink-0 ml-2">MIC OFF</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
