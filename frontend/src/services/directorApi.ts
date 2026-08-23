import type { DirectorState } from '../types/director';

const DIRECTOR_BASE = '/api/director';

async function parseResponse<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error || `${response.status} ${response.statusText}`);
  }
  return body as T;
}

export async function fetchDirectorState(signal?: AbortSignal): Promise<DirectorState> {
  return parseResponse(await fetch(DIRECTOR_BASE, { signal }));
}

export async function runDirectorStage<T>(
  stage: 'discover' | 'attack' | 'qualify' | 'compile' | 'execute',
  payload: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  return parseResponse(await fetch(`${DIRECTOR_BASE}/${stage}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  }));
}
