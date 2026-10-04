import { z } from 'zod';

export const userRoleSchema = z.enum(['admin', 'operator', 'viewer']);

export const tokenResponseSchema = z.object({
  access_token: z.string(),
  refresh_token: z.string(),
  token_type: z.string(),
  expires_in: z.number(),
});

export const userSchema = z.object({
  id: z.string(),
  email: z.string(),
  full_name: z.string(),
  role: userRoleSchema,
  is_active: z.boolean(),
  created_at: z.string(),
});

/** Only admins can change zones, camera links and cameras (the api answers anyone else with 403). */
export function isAdmin(user) {
  return user?.role === 'admin';
}
