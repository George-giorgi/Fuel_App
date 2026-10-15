const STORAGE_KEY = 'diesel-desk-records';
const loginScreen = document.getElementById('loginScreen');
const appScreen = document.getElementById('appScreen');
const fuelForm = document.getElementById('fuelForm');
const historyList = document.getElementById('historyList');
const emptyState = document.getElementById('emptyState');
const recordCount = document.getElementById('recordCount');
const toast = document.getElementById('toast');
const animationStage = document.querySelector('.animation-stage');
const animationMessage = document.getElementById('animationMessage');
const tankLevel = document.getElementById('tankLevel');
const fillPercent = document.getElementById('fillPercent');
const REPORT_EMAIL = 'fleet@yourcompany.com';

let records = [];

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  window.setTimeout(() => toast.classList.remove('show'), 3300);
}

function formatDate(value) {
  return new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function saveRecords() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
}

function renderHistory() {
  emptyState.classList.toggle('hidden', records.length > 0);
  historyList.innerHTML = records.map((record) => `
    <article class="history-item">
      <div><strong>${escapeHtml(record.regNumber)}</strong><small>${escapeHtml(record.firstName)} ${escapeHtml(record.surname)} / ${formatDate(record.createdAt)}</small></div>
      <div class="litres">${record.litres} L</div>
      <button type="button" data-download="${record.id}">Download report .json</button>
    </article>
  `).join('');
  recordCount.textContent = `${records.length} record${records.length === 1 ? '' : 's'}`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
}

function downloadReport(record) {
  const blob = new Blob([JSON.stringify(record, null, 2)], { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `fuel-report-${record.regNumber.replace(/\s+/g, '-')}-${record.id}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function emailReport(record) {
  const subject = `Fuel report: ${record.regNumber} / ${formatDate(record.createdAt)}`;
  const body = [
    'DIESEL DESK FUEL REPORT',
    `Registration: ${record.regNumber}`,
    `Driver: ${record.firstName} ${record.surname}`,
    `Fuel type: ${record.fuelType}`,
    `Mileage: ${record.mileage} km`,
    `Tank capacity: ${record.capacity} litres`,
    `Litres added: ${record.litres} litres`,
    `Cost: ${record.cost ? record.cost : 'Not supplied'}`,
    `Recorded: ${formatDate(record.createdAt)}`
  ].join('\n');
  window.location.href = `mailto:${REPORT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}


document.getElementById('loginForm').addEventListener('submit', async (event) => {
  event.preventDefault();

  const registration = document
    .getElementById('loginRegistration')
    .value.trim()
    .toUpperCase();

  const pin = document.getElementById('loginPin').value;
  const loginError = document.getElementById('loginError');
  const loginButton = document.getElementById('loginButton');

  loginError.textContent = '';
  loginError.classList.add('hidden');
  loginButton.disabled = true;
  loginButton.textContent = 'Signing in...';

  try {
    const loginResponse = await fetch('/api/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      credentials: 'same-origin',
      body: JSON.stringify({ registration, pin })
    });

    const loginData = await loginResponse.json();

    if (!loginResponse.ok) {
      throw new Error(loginData.error || 'Login failed.');
    }

    const dashboardResponse = await fetch('/api/dashboard', {
      method: 'GET',
      credentials: 'same-origin'
    });

    const dashboardData = await dashboardResponse.json();

    if (!dashboardResponse.ok) {
      await fetch('/api/logout', {
        method: 'POST',
        credentials: 'same-origin'
      });

      throw new Error(
        dashboardData.error || 'Could not load dashboard.'
      );
    }

    const employee = dashboardData.employee;
    const vehicle = dashboardData.vehicle;

    document.querySelector('.topbar h2').textContent =
      `Welcome, ${employee.firstName}.`;

    document.getElementById('regNumber').value =
      vehicle.registration;

    document.getElementById('firstName').value =
      employee.firstName;

    document.getElementById('surname').value =
      employee.surname;

    document.getElementById('capacity').value =
      vehicle.tank_capacity_litres ?? '';

    document.getElementById('regNumber').readOnly = true;
    document.getElementById('firstName').readOnly = true;
    document.getElementById('surname').readOnly = true;
    document.getElementById('capacity').readOnly = true;

    document.getElementById('loginPin').value = '';

    loginScreen.classList.add('hidden');
    appScreen.classList.remove('hidden');

    renderHistory();
  } catch (error) {
    loginError.textContent = error.message;
    loginError.classList.remove('hidden');
  } finally {
    loginButton.disabled = false;
    loginButton.innerHTML = 'Sign in <span>→</span>';
  }
});



document.getElementById('logoutButton').addEventListener('click', async () => {
  const logoutButton = document.getElementById('logoutButton');

  logoutButton.disabled = true;

  try {
    const response = await fetch('/api/logout', {
      method: 'POST',
      credentials: 'same-origin'
    });

    const result = await response.json();

    if (!response.ok || !result.success) {
      throw new Error(result.error || 'Could not sign out.');
    }

    // Clear employee and vehicle details from the screen.
    fuelForm.reset();
    document.getElementById('regNumber').readOnly = false;
    document.getElementById('firstName').readOnly = false;
    document.getElementById('surname').readOnly = false;
    document.getElementById('capacity').readOnly = false;

    document.getElementById('loginForm').reset();

    // Clear the dashboard's temporary visual state.
    animationStage.classList.remove('filling');
    tankLevel.style.height = '0%';
    fillPercent.textContent = '0%';
    animationMessage.textContent = 'Ready for the next vehicle';

    // Return to the login screen.
    appScreen.classList.add('hidden');
    loginScreen.classList.remove('hidden');

    showToast('Signed out successfully.');
  } catch (error) {
    showToast(error.message || 'Sign out failed. Please try again.');
  } finally {
    logoutButton.disabled = false;
  }
});



fuelForm.addEventListener('submit', (event) => {
  event.preventDefault();

  showToast(
    'Fuel submissions are temporarily disabled while we connect database saving.'
  );
});


document.getElementById('exportButton').addEventListener('click', () => {
  if (!records.length) {
    showToast('There are no records to export yet.');
    return;
  }
  const blob = new Blob([JSON.stringify(records, null, 2)], { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `diesel-desk-records-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
  showToast('All records exported.');
});

historyList.addEventListener('click', (event) => {
  const id = Number(event.target.dataset.download);
  if (id) downloadReport(records.find((record) => record.id === id));
});

renderHistory();
