
import { supabase } from './supabase.js';

async function testConnection() {
  const { data, error } = await supabase
    .from('vehicles')
    .select('registration, make, model')
    .eq('registration', 'TEST-241');

  if (error) {
    console.error('Supabase error:', error.message);
    return;
  }

  console.log('Vehicle found:', data);
}

testConnection();
