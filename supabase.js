
import { createClient } from '@supabase/supabase-js';

const SUPABASE_URL = 'https://leugkogwtwlwdpkegywr.supabase.co';
const SUPABASE_PUBLISHABLE_KEY = 'sb_publishable_RKMEMy_dLidvixZyHXZKDQ_REHm6oUO';

export const supabase = createClient(
  SUPABASE_URL,
  SUPABASE_PUBLISHABLE_KEY
);
