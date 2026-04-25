import { NextResponse } from "next/server";
import { randomBytes } from "crypto";

function generateId(): string {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  const bytes = randomBytes(8);
  let id = "";
  for (let i = 0; i < 8; i++) {
    id += chars[bytes[i] % chars.length];
  }
  return id;
}

export async function POST() {
  const conferenceId = generateId();
  return NextResponse.json({ conferenceId });
}
