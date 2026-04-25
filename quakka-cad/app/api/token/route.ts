import { NextResponse } from "next/server";

export async function GET() {
  const apiKey = process.env.ELEVENLABS_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { error: "ELEVENLABS_API_KEY not configured" },
      { status: 500 }
    );
  }

  try {
    const res = await fetch(
      "https://api.elevenlabs.io/v1/single-use-token/realtime_scribe",
      {
        method: "POST",
        headers: { "xi-api-key": apiKey },
      }
    );

    if (!res.ok) {
      const body = await res.text();
      return NextResponse.json(
        { error: `ElevenLabs token error: ${res.status} ${body}` },
        { status: 502 }
      );
    }

    const data = await res.json();
    return NextResponse.json({ token: data.token });
  } catch (err) {
    return NextResponse.json(
      { error: `Failed to fetch token: ${err}` },
      { status: 502 }
    );
  }
}
