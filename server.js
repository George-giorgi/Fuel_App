
require('dotenv').config();

const express = require('express');
const rateLimit = require('express-rate-limit');
const { createClient } = require('@supabase/supabase-js');
const bcrypt = require('bcryptjs');
const crypto = require('node:crypto');

const app = express();
const PORT = Number(process.env.PORT) || 3000;
const SESSION_COOKIE = 'diesel_session';
const SESSION_DURATION_MS = 8 * 60 * 60 * 1000;

app.disable('x-powered-by');
app.use(express.json({ limit: '10kb' }));

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseSecret = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!supabaseUrl || !supabaseSecret) {
  console.error('Missing Supabase environment variables in .env');
  process.exit(1);
}

const supabase = createClient(supabaseUrl, supabaseSecret, {
  auth: {
    autoRefreshToken: false,
    persistSession: false
  }
});

const loginLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  limit: 5,
  standardHeaders: 'draft-8',
  legacyHeaders: false,
  message: { error: 'Too many attempts. Please wait and try again.' }
});

function readCookie(req, name) {
  const cookies = (req.headers.cookie || '').split(';');

  for (const cookie of cookies) {
    const separator = cookie.indexOf('=');
    if (separator < 0) continue;

    if (cookie.slice(0, separator).trim() === name) {
      return decodeURIComponent(cookie.slice(separator + 1).trim());
    }
  }

  return null;
}

function setSessionCookie(res, token, maxAgeSeconds) {
  const parts = [
    `${SESSION_COOKIE}=${encodeURIComponent(token)}`,
    'HttpOnly',
    'SameSite=Strict',
    'Path=/',
    `Max-Age=${maxAgeSeconds}`
  ];

  if (process.env.NODE_ENV === 'production') {
    parts.push('Secure');
  }

  res.setHeader('Set-Cookie', parts.join('; '));
}

function clearSessionCookie(res) {
  const parts = [
    `${SESSION_COOKIE}=`,
    'HttpOnly',
    'SameSite=Strict',
    'Path=/',
    'Max-Age=0'
  ];

  if (process.env.NODE_ENV === 'production') {
    parts.push('Secure');
  }

  res.setHeader('Set-Cookie', parts.join('; '));
}

function hashToken(token) {
  return crypto.createHash('sha256').update(token).digest('hex');
}

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

    return res.json({
      status: 'ok',
      service: 'Diesel Desk API',
      database: 'connected'
    });
  } catch (error) {
    console.error('Health check failed:', error.message);
    return res.status(503).json({
      status: 'error',
      service: 'Diesel Desk API',
      database: 'unavailable'
    });
  }
});

app.post('/api/login', loginLimiter, async (req, res) => {
  try {
    const registration =
      typeof req.body?.registration === 'string'
        ? req.body.registration.trim().toUpperCase()
        : '';

    const pin =
      typeof req.body?.pin === 'string' ? req.body.pin : '';

    if (
      !registration ||
      registration.length > 20 ||
      !/^\d{4,8}$/.test(pin)
    ) {
      return res.status(400).json({
        error: 'Enter a valid vehicle registration and PIN.'
      });
    }

    const { data: vehicle, error: vehicleError } = await supabase
      .from('vehicles')
      .select('id, registration, is_active')
      .eq('registration', registration)
      .maybeSingle();

    if (vehicleError) {
      console.error('Vehicle lookup failed:', vehicleError.message);
      return res.status(500).json({ error: 'Login could not be completed.' });
    }

    if (!vehicle || !vehicle.is_active) {
      return res.status(401).json({
        error: 'Invalid registration or PIN.'
      });
    }

    // PINs identify employees in this prototype. Require exactly one match.
    const { data: employees, error: employeeError } = await supabase
      .from('employees')
      .select(
        'id, first_name, surname, role, is_active, pin_hash, pin_failed_attempts, pin_locked_until'
      )
      .not('pin_hash', 'is', null);

    if (employeeError) {
      console.error('Employee lookup failed:', employeeError.message);
      return res.status(500).json({ error: 'Login could not be completed.' });
    }

    const matches = [];

    for (const employee of employees || []) {
      if (await bcrypt.compare(pin, employee.pin_hash)) {
        matches.push(employee);
      }
    }

    if (matches.length !== 1) {
      return res.status(401).json({
        error: 'Invalid registration or PIN.'
      });
    }

    const employee = matches[0];

    if (!employee.is_active) {
      return res.status(401).json({
        error: 'Invalid registration or PIN.'
      });
    }

    if (
      employee.pin_locked_until &&
      new Date(employee.pin_locked_until).getTime() > Date.now()
    ) {
      return res.status(423).json({
        error: 'This PIN is temporarily locked. Contact your manager.'
      });
    }

    const { data: access, error: accessError } = await supabase
      .from('employee_vehicle_access')
      .select('employee_id')
      .eq('employee_id', employee.id)
      .eq('vehicle_id', vehicle.id)
      .maybeSingle();

    if (accessError) {
      console.error('Vehicle permission check failed:', accessError.message);
      return res.status(500).json({ error: 'Login could not be completed.' });
    }

    if (!access) {
      return res.status(403).json({
        error: 'You are not authorised to use this vehicle.'
      });
    }

    const token = crypto.randomBytes(32).toString('base64url');
    const tokenHash = hashToken(token);
    const expiresAt = new Date(Date.now() + SESSION_DURATION_MS);

    const { error: sessionError } = await supabase
      .from('employee_sessions')
      .insert({
        employee_id: employee.id,
        vehicle_id: vehicle.id,
        token_hash: tokenHash,
        expires_at: expiresAt.toISOString()
      });

    if (sessionError) {
      console.error('Session creation failed:', sessionError.message);
      return res.status(500).json({ error: 'Login could not be completed.' });
    }

    // Reset the counter after a successful login.
    const { error: resetError } = await supabase
      .from('employees')
      .update({
        pin_failed_attempts: 0,
        pin_locked_until: null
      })
      .eq('id', employee.id);

    if (resetError) {
      // Do not leave a usable session if the employee record could not be reset.
      await supabase
        .from('employee_sessions')
        .update({ revoked_at: new Date().toISOString() })
        .eq('token_hash', tokenHash);

      console.error('Failed to reset PIN state:', resetError.message);
      return res.status(500).json({ error: 'Login could not be completed.' });
    }

    setSessionCookie(
      res,
      token,
      Math.floor(SESSION_DURATION_MS / 1000)
    );

    return res.json({
      success: true,
      employee: {
        firstName: employee.first_name,
        surname: employee.surname,
        role: employee.role
      },
      vehicle: {
        registration: vehicle.registration
      },
      expiresAt: expiresAt.toISOString()
    });
  } catch (error) {
    console.error('Login error:', error.message);
    return res.status(500).json({ error: 'Login could not be completed.' });
  }
});

async function requireSession(req, res, next) {
  try {
    const token = readCookie(req, SESSION_COOKIE);

    if (!token) {
      return res.status(401).json({
        authenticated: false,
        error: 'Please log in.'
      });
    }

    const { data: session, error } = await supabase
      .from('employee_sessions')
      .select(`
        id,
        employee_id,
        vehicle_id,
        expires_at,
        revoked_at,
        employees (
          first_name,
          surname,
          role,
          is_active
        ),
        vehicles (
          registration,
          is_active
        )
      `)
      .eq('token_hash', hashToken(token))
      .maybeSingle();

    if (error) {
      console.error('Session lookup failed:', error.message);
      return res.status(500).json({
        error: 'Could not verify session.'
      });
    }

    if (
      !session ||
      session.revoked_at ||
      new Date(session.expires_at).getTime() <= Date.now()
    ) {
      clearSessionCookie(res);

      return res.status(401).json({
        authenticated: false,
        error: 'Session expired. Please log in again.'
      });
    }

    if (
      !session.employees?.is_active ||
      !session.vehicles?.is_active
    ) {
      clearSessionCookie(res);

      return res.status(401).json({
        authenticated: false,
        error: 'Access is no longer available. Please log in again.'
      });
    }

    req.employee = {
      id: session.employee_id,
      firstName: session.employees.first_name,
      surname: session.employees.surname,
      role: session.employees.role
    };

    req.vehicle = {
      id: session.vehicle_id,
      registration: session.vehicles.registration
    };

    req.sessionId = session.id;

    return next();
  } catch (error) {
    console.error('Session middleware failed:', error.message);

    return res.status(500).json({
      error: 'Could not verify session.'
    });
  }
}


app.get('/api/dashboard', requireSession, async (req, res) => {
  try {
    const { data: vehicle, error } = await supabase
      .from('vehicles')
      .select(`
        id,
        registration,
        make,
        model,
        tank_capacity_litres,
        last_cumulative_reading,
        last_fill_litres,
        last_vehicle_mileage
      `)
      .eq('id', req.vehicle.id)
      .eq('is_active', true)
      .maybeSingle();

    if (error) {
      console.error('Dashboard vehicle query failed:', error.message);

      return res.status(500).json({
        success: false,
        error: 'Unable to load vehicle details.'
      });
    }

    if (!vehicle) {
      return res.status(404).json({
        success: false,
        error: 'Vehicle not found or inactive.'
      });
    }

    return res.json({
      success: true,
      employee: req.employee,
      vehicle,
      message: 'Dashboard data loaded successfully.'
    });
  } catch (error) {
    console.error('Dashboard error:', error.message);

    return res.status(500).json({
      success: false,
      error: 'An unexpected error occurred.'
    });
  }
});


app.get('/api/fuel-transactions', requireSession, async (req, res) => {
  try {
    const { data, error } = await supabase
      .from('fuel_transactions')
      .select(`
        id,
        vehicle_mileage,
        previous_cumulative_reading,
        new_cumulative_reading,
        litres_added,
        verification_status,
        created_at,
        employees (
          first_name,
          surname
        )
      `)
      .eq('vehicle_id', req.vehicle.id)
      .order('created_at', { ascending: false })
      .limit(50);

    if (error) {
      console.error('Fuel history query failed:', error.message);
      return res.status(500).json({
        success: false,
        error: 'Could not load fuel history.'
      });
    }

    return res.json({
      success: true,
      transactions: (data || []).map((item) => ({
        id: item.id,
        mileage: item.vehicle_mileage,
        previousReading: item.previous_cumulative_reading,
        newReading: item.new_cumulative_reading,
        litresAdded: item.litres_added,
        status: item.verification_status,
        createdAt: item.created_at,
        firstName: item.employees?.first_name || '',
        surname: item.employees?.surname || ''
      }))
    });
  } catch (error) {
    console.error('Fuel history error:', error.message);
    return res.status(500).json({
      success: false,
      error: 'Could not load fuel history.'
    });
  }
});


app.get('/api/session', async (req, res) => {
  try {
    const token = readCookie(req, SESSION_COOKIE);

    if (!token) {
      return res.status(401).json({
        authenticated: false,
        error: 'Please log in.'
      });
    }

    const tokenHash = hashToken(token);

    const { data: session, error } = await supabase
      .from('employee_sessions')
      .select(`
        id,
        employee_id,
        vehicle_id,
        expires_at,
        revoked_at,
        employees (
          first_name,
          surname,
          role,
          is_active
        ),
        vehicles (
          registration,
          is_active
        )
      `)
      .eq('token_hash', tokenHash)
      .maybeSingle();

    if (error) {
      console.error('Session lookup failed:', error.message);
      return res.status(500).json({
        error: 'Could not verify session.'
      });
    }

    if (
      !session ||
      session.revoked_at ||
      new Date(session.expires_at).getTime() <= Date.now()
    ) {
      clearSessionCookie(res);

      return res.status(401).json({
        authenticated: false,
        error: 'Session expired. Please log in again.'
      });
    }

    const employee = session.employees;
    const vehicle = session.vehicles;

    if (
      !employee ||
      !employee.is_active ||
      !vehicle ||
      !vehicle.is_active
    ) {
      clearSessionCookie(res);

      return res.status(401).json({
        authenticated: false,
        error: 'Access is no longer available. Please log in again.'
      });
    }

    return res.json({
      authenticated: true,
      employee: {
        firstName: employee.first_name,
        surname: employee.surname,
        role: employee.role
      },
      vehicle: {
        registration: vehicle.registration
      },
      expiresAt: session.expires_at
    });
  } catch (error) {
    console.error('Session verification failed:', error.message);

    return res.status(500).json({
      error: 'Could not verify session.'
    });
  }
});


app.post('/api/logout', async (req, res) => {
  try {
    const token = readCookie(req, SESSION_COOKIE);

    if (token) {
      await supabase
        .from('employee_sessions')
        .update({ revoked_at: new Date().toISOString() })
        .eq('token_hash', hashToken(token))
        .is('revoked_at', null);
    }

    clearSessionCookie(res);
    return res.json({ success: true });
  } catch (error) {
    console.error('Logout error:', error.message);
    clearSessionCookie(res);
    return res.status(500).json({ error: 'Logout could not be completed.' });
  }
});


app.post('/api/fuel-transactions', requireSession, async (req, res) => {
  try {
    const rawReading = req.body?.newCumulativeReading;
    const rawMileage = req.body?.vehicleMileage;

    // Accept decimal readings with up to two decimal places.
    const readingText =
      typeof rawReading === 'number' || typeof rawReading === 'string'
        ? String(rawReading).trim()
        : '';

    if (!/^\d{1,10}(\.\d{1,2})?$/.test(readingText)) {
      return res.status(400).json({
        success: false,
        error: 'Enter a valid meter reading with up to two decimal places.'
      });
    }

    const newReading = Number(readingText);
    
    if (!Number.isSafeInteger(Number(rawMileage)) ||
        !Number.isInteger(Number(rawMileage)) ||
        Number(rawMileage) < 0 ||
        String(rawMileage).trim() === '') {
      return res.status(400).json({
        success: false,
        error: 'Enter a valid whole-number vehicle mileage.'
      });
    }

    const { data, error } = await supabase.rpc(
      'record_fuel_transaction',
      {
        p_employee_id: req.employee.id,
        p_vehicle_id: req.vehicle.id,
        p_vehicle_mileage: Number(rawMileage),
        p_new_cumulative_reading: newReading,
        p_meter_photo_path: null
      }
    );

    if (error) {
      console.error('Fuel transaction failed:', error.message);

      return res.status(400).json({
        success: false,
        error: error.message.includes('New reading must be greater')
          ? 'The new reading must be greater than the previous meter reading.'
          : 'The fuel transaction could not be saved. Check the reading and try again.'
      });
    }

    const transaction = data?.[0];

    if (!transaction) {
      return res.status(500).json({
        success: false,
        error: 'The transaction was not returned by the database.'
      });
    }

    return res.status(201).json({
      success: true,
      transaction: {
        id: transaction.transaction_id,
        previousReading: transaction.previous_reading,
        newReading: transaction.new_reading,
        litresAdded: transaction.litres_added
      }
    });
  } catch (error) {
    console.error('Unexpected fuel transaction error:', error.message);

    return res.status(500).json({
      success: false,
      error: 'An unexpected error occurred while saving the transaction.'
    });
  }
});


app.listen(PORT, () => {
  console.log(`Diesel Desk API running on http://localhost:${PORT}`);
});
