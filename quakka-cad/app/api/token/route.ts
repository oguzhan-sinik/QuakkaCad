const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function GET() {
  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/api/token`);
  } catch (e) {
    return Response.json({ error: `Upstream error: ${e}` }, { status: 502 });
  }

  const body = await upstream.arrayBuffer();
  return new Response(body, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
