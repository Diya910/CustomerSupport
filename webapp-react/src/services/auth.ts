export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  role: string;
}

export interface AuthError {
  detail: string;
}

export async function loginWithCredentials(
  username: string,
  password: string
): Promise<LoginResponse> {
  const response = await fetch(`${import.meta.env.BASE_URL}auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });

  if (!response.ok) {
    const err: AuthError = await response.json().catch(() => ({ detail: 'Login failed' }));
    throw new Error(err.detail ?? 'Login failed');
  }

  return response.json() as Promise<LoginResponse>;
}
