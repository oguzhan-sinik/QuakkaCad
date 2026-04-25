export const maxDuration = 300;

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function POST(
  _req: Request,
  { params }: { params: Promise<{ meetingId: string }> }
) {
  const { meetingId } = await params;
  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/api/meetings/${meetingId}/agent/plan`, {
      method: "POST",
    });
  } catch (e) {
    return Response.json({ detail: `Upstream error: ${e}` }, { status: 502 });
  }
  const body = await upstream.arrayBuffer();
  return new Response(body, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
