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

function formatMiles(miles) {
  return miles.toLocaleString('en-IE', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1
  });
}

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers
    }
  });
  const responseText = await response.text();
  let result;
  try {
    result = responseText ? JSON.parse(responseText) : null;
  } catch (error) {
    if (response.ok) throw error;
    throw new Error(`Request failed (${response.status})`);
  }
  if (!response.ok) {
    throw new Error(result?.detail || `Request failed (${response.status})`);
  }
  return result;
}

async function loadRecords() {
  try {
    records = await apiRequest('/api/fuel-records');
    renderHistory();
  } catch (error) {
    showToast(`Could not load fuel records: ${error.message}`);
  }
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
  const blob = new Blob([JSON.stringify({
    ...record,
    mileageUnit: 'mi'
  }, null, 2)], { type: 'application/json' });
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
    `Mileage: ${formatMiles(record.mileageMiles)} mi`,
    `Tank capacity: ${record.capacity} litres`,
    `Litres added: ${record.litres} litres`,
    `Cost: ${record.cost ? record.cost : 'Not supplied'}`,
    `Recorded: ${formatDate(record.createdAt)}`
  ].join('\n');
  window.location.href = `mailto:${REPORT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

document.getElementById('loginForm').addEventListener('submit', (event) => {
  event.preventDefault();
  loginScreen.classList.add('hidden');
  appScreen.classList.remove('hidden');
  renderHistory();
});

document.getElementById('logoutButton').addEventListener('click', () => {
  appScreen.classList.add('hidden');
  loginScreen.classList.remove('hidden');
});

fuelForm.addEventListener('submit', (event) => {
  event.preventDefault();
  showToast('Fuel submissions are disabled until meter verification is ready.');
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

loadRecords();
