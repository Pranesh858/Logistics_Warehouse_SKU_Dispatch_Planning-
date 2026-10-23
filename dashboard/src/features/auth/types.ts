export type Role = 'admin' | 'planner' | 'viewer';

export interface AuthUser {
  id: number;
  username: string;
  name: string;
  role: Role;
  warehouse_id: string | null;
  active: boolean;
  must_change_password?: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface LoginResult {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

export const ROLE_LABEL: Record<Role, string> = { admin: 'Planning admin', planner: 'Planner', viewer: 'Viewer' };
