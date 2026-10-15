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
      <div>
        <strong>${escapeHtml(document.getElementById('regNumber').value)}</strong>
        <small>
          ${escapeHtml(record.firstName)} ${escapeHtml(record.surname)}
          / ${formatDate(record.createdAt)}
        </small>
        <small>
          Meter: ${Number(record.previousReading).toFixed(2)}
          → ${Number(record.newReading).toFixed(2)}
        </small>
        <small>
          Mileage: ${Number(record.mileage).toLocaleString('en-IE')} km
          / Status: ${escapeHtml(record.status)}
        </small>
      </div>
      <div class="litres">
        ${Number(record.litresAdded).toFixed(2)} L
      </div>
    </article>
  `).join('');

  recordCount.textContent =
    `${records.length} record${records.length === 1 ? '' : 's'}`;
}


async function loadFuelHistory() {
  const response = await fetch('/api/fuel-transactions', {
    method: 'GET',
    credentials: 'same-origin'
  });

  const result = await response.json();

  if (!response.ok || !result.success) {
    throw new Error(result.error || 'Could not load fuel history.');
  }

  records = result.transactions;
  renderHistory();
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
    isManager = employee.role === 'manager';

deliveriesNav.classList.toggle('hidden', !isManager);

inventoryNav.classList.toggle('hidden', !isManager);

deliveriesSection.classList.add('hidden');
document.querySelector('.dashboard-grid').classList.remove('hidden');

document.querySelectorAll('.sidebar nav a').forEach((link) => {
  link.classList.remove('active');
});

document.querySelector('.sidebar nav a[href="#newFill"]')
  .classList.add('active');
    const vehicle = dashboardData.vehicle;
    
document.getElementById('vehicleRegistration').textContent =
  vehicle.registration || '—';

document.getElementById('vehicleDescription').textContent =
  [vehicle.make, vehicle.model].filter(Boolean).join(' ') ||
  'Make and model not recorded';

document.getElementById('vehicleCapacity').textContent =
  vehicle.tank_capacity_litres ?? '—';

document.getElementById('vehicleCumulative').textContent =
  vehicle.last_cumulative_reading ?? '—';

document.getElementById('vehicleLastFill').textContent =
  vehicle.last_fill_litres ?? '—';

document.getElementById('vehicleMileage').textContent =
  vehicle.last_vehicle_mileage == null
    ? '—'
    : Number(vehicle.last_vehicle_mileage).toLocaleString('en-IE');


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

    try {
  await loadFuelHistory();
} catch (error) {
  showToast(error.message || 'Could not load fuel history.');
}renderHistory();
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
    isManager = false;
deliveriesNav.classList.add('hidden');
deliveriesSection.classList.add('hidden');
document.querySelector('.dashboard-grid').classList.remove('hidden');
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





fuelForm.addEventListener('submit', async (event) => {
  event.preventDefault();

  const submitButton = fuelForm.querySelector('button[type="submit"]');
  const readingInput = document.getElementById('newCumulativeReading');
  const mileageInput = document.getElementById('mileage');

  const readingText = readingInput.value.trim();
  const mileageText = mileageInput.value.trim();
  const mileage = Number(mileageText);
  const newCumulativeReading = Number(readingText);

  if (!/^\d{1,10}(\.\d{1,2})?$/.test(readingText)) {
    showToast('Enter a meter reading with up to 2 decimal places.');
    return;
  }

  if (
    mileageText === '' ||
    !Number.isSafeInteger(mileage) ||
    mileage < 0
  ) {
    showToast('Enter a valid whole-number vehicle mileage.');
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = 'Saving...';

  try {
    const response = await fetch('/api/fuel-transactions', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        newCumulativeReading,
        vehicleMileage: mileage
      })
    });

    const result = await response.json();

    if (!response.ok || !result.success) {
      throw new Error(
        result.error || 'Could not save the fuel transaction.'
      );
    }

    const transaction = result.transaction;

    document.getElementById('vehicleCumulative').textContent =
      Number(transaction.newReading).toFixed(2);

    document.getElementById('vehicleLastFill').textContent =
      Number(transaction.litresAdded).toFixed(2);

    document.getElementById('vehicleMileage').textContent =
      mileage.toLocaleString('en-IE');
    
    
await loadFuelHistory();


    // Refresh the animation.
    const capacity = Number(
      document.getElementById('capacity').value
    );

    const litresAdded = Number(transaction.litresAdded);
    const percent = capacity > 0
      ? Math.min(100, (litresAdded / capacity) * 100)
      : 0;

    animationStage.classList.add('filling');
    tankLevel.style.height = `${percent}%`;
    fillPercent.textContent = `${Math.round(percent)}%`;
    animationMessage.textContent =
      `Recorded ${litresAdded.toFixed(2)} litres`;

    readingInput.value = '';

    showToast(
      `Fuel record saved: ${litresAdded.toFixed(2)} litres.`
    );
  } catch (error) {
    showToast(error.message || 'Fuel submission failed.');
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = 'Save fill report <span>-></span>';
  }
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


const deliveriesNav = document.getElementById('deliveriesNav');
const inventoryNav = document.getElementById('inventoryNav');
const deliveriesSection = document.getElementById('dieselDeliveries');
const deliveryForm = document.getElementById('deliveryForm');
const deliveriesList = document.getElementById('deliveriesList');
const deliveryError = document.getElementById('deliveryError');

let isManager = false;

function showDeliveryError(message) {
  deliveryError.textContent = message;
  deliveryError.classList.remove('hidden');
}

function hideDeliveryError() {
  deliveryError.textContent = '';
  deliveryError.classList.add('hidden');
}

function formatEuro(value) {
  return new Intl.NumberFormat('en-IE', {
    style: 'currency',
    currency: 'EUR'
  }).format(Number(value));
}

async function loadDieselDeliveries() {
  if (!isManager) return;

  deliveriesList.innerHTML = '<p>Loading deliveries...</p>';

  const response = await fetch('/api/diesel-deliveries', {
    method: 'GET',
    credentials: 'same-origin'
  });

  const result = await response.json();

  if (!response.ok || !result.success) {
    throw new Error(result.error || 'Could not load diesel deliveries.');
  }

  if (!result.deliveries.length) {
    deliveriesList.innerHTML =
      '<p>No supplier invoices recorded yet.</p>';
    return;
  }

  deliveriesList.innerHTML = result.deliveries.map((delivery) => `
    <article class="history-item">
      <div>
        <strong>${escapeHtml(delivery.supplier_name)}</strong>
        <small>
          Date: ${escapeHtml(delivery.delivery_date)}
          ${delivery.invoice_reference
            ? ` / Invoice: ${escapeHtml(delivery.invoice_reference)}`
            : ''}
        </small>
        <small>
          Delivered: ${Number(delivery.litres_delivered).toLocaleString('en-IE')} L
        </small>
        <small>
          Ex VAT: ${formatEuro(delivery.invoice_total_ex_vat)}
          / Inc VAT: ${formatEuro(delivery.invoice_total_inc_vat)}
        </small>
        <small>
          Price per litre ex VAT: ${formatEuro(delivery.price_per_litre_ex_vat)}
          / Inc VAT: ${formatEuro(delivery.price_per_litre_inc_vat)}
        </small>
        ${delivery.notes
          ? `<small>Notes: ${escapeHtml(delivery.notes)}</small>`
          : ''}
      </div>
    </article>
  `).join('');
}

deliveryForm.addEventListener('submit', async (event) => {
  event.preventDefault();

  if (!isManager) {
    showDeliveryError('Manager access required.');
    return;
  }

  hideDeliveryError();

  const submitButton = deliveryForm.querySelector(
    'button[type="submit"]'
  );

  const payload = {
    deliveryDate: document.getElementById('deliveryDate').value,
    supplierName: document.getElementById('supplierName').value.trim(),
    invoiceReference: document.getElementById('invoiceReference').value.trim(),
    litresDelivered: document.getElementById('litresDelivered').value,
    invoiceTotalExVat: document.getElementById('invoiceTotalExVat').value,
    invoiceTotalIncVat: document.getElementById('invoiceTotalIncVat').value,
    notes: document.getElementById('deliveryNotes').value.trim()
  };

  submitButton.disabled = true;
  submitButton.textContent = 'Saving invoice...';

  try {
    const response = await fetch('/api/diesel-deliveries', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    const result = await response.json();

    if (!response.ok || !result.success) {
      throw new Error(result.error || 'Could not save the supplier invoice.');
    }

    deliveryForm.reset();
    hideDeliveryError();

    await loadDieselDeliveries();
    showToast('Supplier invoice saved successfully.');
  } catch (error) {
    showDeliveryError(error.message || 'Could not save the supplier invoice.');
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = 'Save supplier invoice <span>→</span>';
  }
});

document.getElementById('refreshDeliveriesButton')
  .addEventListener('click', async () => {
    try {
      await loadDieselDeliveries();
    } catch (error) {
      showDeliveryError(error.message);
    }
  });

deliveriesNav.addEventListener('click', async (event) => {
  event.preventDefault();

  if (!isManager) return;

  document.querySelector('.dashboard-grid').classList.add('hidden');
  deliveriesSection.classList.remove('hidden');

  document.querySelectorAll('.sidebar nav a').forEach((link) => {
    link.classList.remove('active');
  });

  deliveriesNav.classList.add('active');

  try {
    await loadDieselDeliveries();
  } catch (error) {
    showDeliveryError(error.message);
  }
});

document.querySelectorAll('.sidebar nav a[href="#newFill"], .sidebar nav a[href="#history"]')
  .forEach((link) => {
    link.addEventListener('click', () => {
      document.querySelector('.dashboard-grid').classList.remove('hidden');
      deliveriesSection.classList.add('hidden');

      document.querySelectorAll('.sidebar nav a').forEach((item) => {
        item.classList.remove('active');
      });

      link.classList.add('active');
    });
  });

document.getElementById('deliveryDate').value =
  new Date().getFullYear() + '-' +
  String(new Date().getMonth() + 1).padStart(2, '0') + '-' +
  String(new Date().getDate()).padStart(2, '0');


const inventorySection = document.getElementById('dieselInventory');
const inventoryStatus = document.getElementById('inventoryStatus');
const inventorySummary = document.getElementById('inventorySummary');
const openingStockPanel = document.getElementById('openingStockPanel');
const openingStockForm = document.getElementById('openingStockForm');
const openingStockError = document.getElementById('openingStockError');

function setInventoryError(message) {
  inventoryStatus.textContent = message;
  inventorySummary.classList.add('hidden');
}

async function loadDieselInventory() {
  if (!isManager) return;

  inventoryStatus.textContent = 'Loading inventory...';
  inventorySummary.classList.add('hidden');

  const response = await fetch('/api/diesel-inventory', {
    method: 'GET',
    credentials: 'same-origin'
  });

  const result = await response.json();

  if (!response.ok || !result.success) {
    throw new Error(result.error || 'Could not load diesel inventory.');
  }

  const stock = result.inventory;

  if (!stock.is_initialized) {
    inventoryStatus.textContent =
      'Opening stock has not been initialized. Enter the real opening figures when they are available.';
    openingStockPanel.classList.remove('hidden');
    inventorySummary.classList.add('hidden');
    return;
  }

  const litres = Number(stock.litres_on_hand);
  const valueEx = Number(stock.stock_value_ex_vat);
  const valueInc = Number(stock.stock_value_inc_vat);

  document.getElementById('inventoryLitres').textContent =
    litres.toLocaleString('en-IE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  document.getElementById('inventoryValueExVat').textContent =
    valueEx.toLocaleString('en-IE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  document.getElementById('inventoryValueIncVat').textContent =
    valueInc.toLocaleString('en-IE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  document.getElementById('inventoryUnitExVat').textContent =
    litres > 0 ? formatEuro(valueEx / litres) : '—';

  document.getElementById('inventoryUnitIncVat').textContent =
    litres > 0 ? formatEuro(valueInc / litres) : '—';

  inventoryStatus.textContent = 'Inventory loaded successfully.';
  inventorySummary.classList.remove('hidden');
  openingStockPanel.classList.add('hidden');
}

inventoryNav.addEventListener('click', async (event) => {
  event.preventDefault();

  if (!isManager) return;

  document.querySelector('.dashboard-grid').classList.add('hidden');
  deliveriesSection.classList.add('hidden');
  inventorySection.classList.remove('hidden');

  document.querySelectorAll('.sidebar nav a').forEach((link) => {
    link.classList.remove('active');
  });

  inventoryNav.classList.add('active');

  try {
    await loadDieselInventory();
  } catch (error) {
    setInventoryError(error.message || 'Could not load diesel inventory.');
  }
});

document.getElementById('refreshInventoryButton')
  .addEventListener('click', async () => {
    try {
      await loadDieselInventory();
    } catch (error) {
      setInventoryError(error.message || 'Could not refresh inventory.');
    }
  });

openingStockForm.addEventListener('submit', async (event) => {
  event.preventDefault();

  if (!isManager) {
    openingStockError.textContent = 'Manager access required.';
    openingStockError.classList.remove('hidden');
    return;
  }

  openingStockError.textContent = '';
  openingStockError.classList.add('hidden');

  const submitButton = openingStockForm.querySelector('button[type="submit"]');

  const payload = {
    litres: document.getElementById('openingLitres').value,
    valueExVat: document.getElementById('openingValueExVat').value,
    valueIncVat: document.getElementById('openingValueIncVat').value,
    notes: document.getElementById('openingStockNotes').value.trim()
  };

  submitButton.disabled = true;
  submitButton.textContent = 'Initializing...';

  try {
    const response = await fetch('/api/diesel-inventory/initialize', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const result = await response.json();

    if (!response.ok || !result.success) {
      throw new Error(result.error || 'Could not initialize opening stock.');
    }

    openingStockForm.reset();
    await loadDieselInventory();
    showToast('Opening stock initialized successfully.');
  } catch (error) {
    openingStockError.textContent =
      error.message || 'Could not initialize opening stock.';
    openingStockError.classList.remove('hidden');
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = 'Initialize opening stock <span>→</span>';
  }
});

// Hide the inventory screen when navigating to other sections.
document.querySelectorAll(
  '.sidebar nav a[href="#newFill"], .sidebar nav a[href="#history"]'
).forEach((link) => {
  link.addEventListener('click', () => {
    inventorySection.classList.add('hidden');
  });
});

deliveriesNav.addEventListener('click', () => {
  inventorySection.classList.add('hidden');
});

// Ensure the inventory screen is hidden after logout.
document.getElementById('logoutButton').addEventListener('click', () => {
  inventorySection.classList.add('hidden');
  inventoryNav.classList.add('hidden');
});


