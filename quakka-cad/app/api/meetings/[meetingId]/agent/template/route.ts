export const maxDuration = 300;

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ meetingId: string }> }
) {
  const { meetingId } = await params;
  const body = await req.text();
  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/api/meetings/${meetingId}/agent/template`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
  } catch (e) {
    return Response.json({ detail: `Upstream error: ${e}` }, { status: 502 });
  }

  const respBody = await upstream.arrayBuffer();
  return new Response(respBody, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
