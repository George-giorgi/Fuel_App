
require('dotenv').config();

const express = require('express');
const rateLimit = require('express-rate-limit');
const { createClient } = require('@supabase/supabase-js');

const app = express();
const PORT = Number(process.env.PORT) || 3000;

app.disable('x-powered-by');
app.use(express.json({ limit: '10kb' }));

// Create a server-only Supabase connection.
const supabaseUrl = process.env.SUPABASE_URL;
const supabaseSecret =
  process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!supabaseUrl || !supabaseSecret) {
  console.error(
    'Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env'
  );
  process.exit(1);
}

const supabase = createClient(supabaseUrl, supabaseSecret, {
  auth: {
    autoRefreshToken: false,
    persistSession: false
  }
});

// Basic health check. Does not reveal credentials.

app.get('/health', async (req, res) => {
  try {
    const { error } = await supabase
      .from('vehicles')
      .select('id')
      .limit(1);

    if (error) {
      console.error('Database health check failed:', error.message);

      return res.status(503).json({
        status: 'error',
        service: 'Diesel Desk API',
        database: 'unavailable'
      });
    }

    res.json({
      status: 'ok',
      service: 'Diesel Desk API',
      database: 'connected'
    });
  } catch (error) {
    console.error('Health check failed:', error.message);

    res.status(503).json({
      status: 'error',
      service: 'Diesel Desk API',
      database: 'unavailable'
    });
  }
});


// Limit repeated requests to this API endpoint.
const loginLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  limit: 10,
  standardHeaders: 'draft-8',
  legacyHeaders: false,
  message: {
    error: 'Too many attempts. Please wait and try again.'
  }
});

// Placeholder for the secure employee PIN login.
app.post('/api/login', loginLimiter, (req, res) => {
  res.status(501).json({
    error: 'PIN login is not implemented yet.'
  });
});

app.listen(PORT, () => {
  console.log(`Diesel Desk API running on http://localhost:${PORT}`);
});
