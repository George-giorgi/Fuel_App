function formatErrorDetail(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map(formatErrorDetail).filter(Boolean).join('; ');
  }
  if (detail && typeof detail === 'object') {
    const message =
      typeof detail.msg === 'string'
        ? detail.msg
        : typeof detail.message === 'string'
          ? detail.message
          : JSON.stringify(detail);
    const location = Array.isArray(detail.loc) ? detail.loc.join('.') : '';
    return location ? `${location}: ${message}` : message;
  }
  return '';
}

async function apiRequest(path, options = {}) {
  const isFormData =
    typeof FormData !== 'undefined' && options.body instanceof FormData;
  const response = await fetch(path, {
    ...options,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(options.body && !isFormData
        ? { 'Content-Type': 'application/json' }
        : {}),
      ...options.headers
    }
  });
  const responseText = await response.text();
  let result = null;
  if (responseText) {
    try {
      result = JSON.parse(responseText);
    } catch (error) {
      if (response.ok) throw error;
    }
  }
  if (!response.ok) {
    const detailMessage = formatErrorDetail(result?.detail);
    const requestError = new Error(
      detailMessage || `Request failed (${response.status})`
    );
    requestError.status = response.status;
    requestError.path = path;
    throw requestError;
  }
  return result;
}

export function login(username, password) {
  return apiRequest('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password })
  });
}

export function logout() {
  return apiRequest('/api/auth/logout', { method: 'POST' });
}

export function getCurrentEmployee() {
  return apiRequest('/api/auth/me');
}

export function getFuelRecords() {
  return apiRequest('/api/fuel-records');
}

export function getVehicleFuelRecords() {
  return apiRequest('/api/vehicles/me/fuel-records');
}

export function createFuelRecord(record) {
  return apiRequest('/api/fuel-records', {
    method: 'POST',
    body: JSON.stringify(record)
  });
}

export function getAssignedVehicle() {
  return apiRequest('/api/vehicles/me');
}

export function identifyVehicle(registrationNumber) {
  return apiRequest(
    `/api/vehicles/lookup/${encodeURIComponent(registrationNumber.trim())}`
  );
}

export function createEmployee(employee) {
  return apiRequest('/api/admin/employees', {
    method: 'POST',
    body: JSON.stringify(employee)
  });
}

export function updateEmployeeRole(employeeId, role) {
  return apiRequest(`/api/admin/employees/${employeeId}/role`, {
    method: 'PATCH',
    body: JSON.stringify({ role })
  });
}

export function updateEmployeeStatus(employeeId, isActive) {
  return apiRequest(`/api/admin/employees/${employeeId}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ isActive })
  });
}

export function createVehicle(vehicle) {
  return apiRequest('/api/admin/vehicles', {
    method: 'POST',
    body: JSON.stringify(vehicle)
  });
}

export function getAdminVehicles() {
  return apiRequest('/api/admin/vehicles');
}

export function getNctAlerts() {
  return apiRequest('/api/admin/nct-alerts');
}

export function getVehicleNctList() {
  return apiRequest('/api/admin/vehicles/nct');
}

export function updateVehicleNct(vehicleId, nctExpiryDate) {
  return apiRequest(`/api/admin/vehicles/${vehicleId}/nct`, {
    method: 'PATCH',
    body: JSON.stringify({ nctExpiryDate })
  });
}

export function getAdminEmployees() {
  return apiRequest('/api/admin/employees');
}

export function getAdminEmployeeFuelRecords(employeeId, dateRange = {}) {
  const query = new URLSearchParams();
  if (dateRange.startDate) query.set('start_date', dateRange.startDate);
  if (dateRange.endDate) query.set('end_date', dateRange.endDate);
  const queryString = query.toString();
  const suffix = queryString ? `?${queryString}` : '';
  return apiRequest(
    `/api/admin/employees/${employeeId}/fuel-records${suffix}`
  );
}

export function getAdminFuelSummary(dateRange = {}) {
  const query = new URLSearchParams();
  if (dateRange.startDate) query.set('start_date', dateRange.startDate);
  if (dateRange.endDate) query.set('end_date', dateRange.endDate);
  const queryString = query.toString();
  const suffix = queryString ? `?${queryString}` : '';
  return apiRequest(`/api/admin/fuel-summary${suffix}`);
}

export function getExecutiveDashboard() {
  return apiRequest('/api/executive/dashboard');
}

export function getExecutiveAnalytics(rangeDays = 30) {
  const query = new URLSearchParams({ range_days: String(rangeDays) });
  return apiRequest(`/api/executive/analytics?${query}`);
}

export function getExecutiveVehicles(filters = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== '' && value != null) query.set(key, String(value));
  }
  const suffix = query.toString() ? `?${query}` : '';
  return apiRequest(`/api/executive/vehicles${suffix}`);
}

export function getExecutiveEmployees(filters = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== '' && value != null) query.set(key, String(value));
  }
  const suffix = query.toString() ? `?${query}` : '';
  return apiRequest(`/api/executive/employees${suffix}`);
}

export function getExecutiveEmployeeFuelRecords(employeeId, filters = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== '' && value != null) query.set(key, String(value));
  }
  const suffix = query.toString() ? `?${query}` : '';
  return apiRequest(
    `/api/executive/employees/${employeeId}/fuel-records${suffix}`
  );
}

export function getExecutiveVehicle(vehicleId) {
  return apiRequest(`/api/executive/vehicles/${vehicleId}`);
}

export function getMyVehicle() {
  return apiRequest('/api/executive/my-vehicle');
}

export function setMyVehicle(vehicleId) {
  return apiRequest('/api/executive/my-vehicle', {
    method: 'PUT',
    body: JSON.stringify({ vehicle_id: vehicleId })
  });
}

export function provisionVehicleQr(vehicleId) {
  return apiRequest(`/api/admin/vehicles/${vehicleId}/qr-code`, {
    method: 'POST'
  });
}

export function startQrSession(qrPayload) {
  return apiRequest('/api/qr/sessions', {
    method: 'POST',
    body: JSON.stringify({ qr_payload: qrPayload })
  });
}

export function startMeterPhotoSession() {
  return apiRequest('/api/meter-photos/sessions', { method: 'POST' });
}

export function uploadMeterPhoto(sessionToken, photo) {
  const body = new FormData();
  body.append('session_token', sessionToken);
  body.append('photo', photo);
  return apiRequest('/api/meter-photos', { method: 'POST', body });
}

export function verifyMeterPhoto(meterPhotoId, readings) {
  return apiRequest(`/api/meter-photos/${meterPhotoId}/verify`, {
    method: 'PATCH',
    body: JSON.stringify(readings)
  });
}

export function createVehicleMeterEvent(vehicleId, event) {
  return apiRequest(`/api/admin/vehicles/${vehicleId}/meter-events`, {
    method: 'POST',
    body: JSON.stringify(event)
  });
}

export function getGlobalMeterSummary() {
  return apiRequest('/api/management/global-meter');
}

export function getGlobalMeterHistory() {
  return apiRequest('/api/management/global-meter/history?limit=200');
}

export function createGlobalMeterEvent(event) {
  return apiRequest('/api/management/global-meter/events', {
    method: 'POST',
    body: JSON.stringify(event)
  });
}
