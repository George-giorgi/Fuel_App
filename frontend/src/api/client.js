const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');

export function apiUrl(path) {
  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

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
  const response = await fetch(apiUrl(path), {
    ...options,
    credentials: 'include',
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

export function previewFuelReading(reading) {
  return apiRequest('/api/fuel-records/preview', {
    method: 'POST',
    body: JSON.stringify(reading)
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

export async function getVehicleRegistrationSuggestions(search = '') {
  const query = new URLSearchParams();
  if (search.trim()) query.set('search', search.trim());
  const suffix = query.toString() ? `?${query}` : '';
  try {
    return await apiRequest(`/api/vehicles/suggestions${suffix}`);
  } catch (requestError) {
    if (requestError.status !== 404) throw requestError;

    const result = await getExecutiveVehicles({
      page: 1,
      page_size: 100,
      search,
      sort_by: 'registration',
      sort_order: 'asc',
      status: 'active'
    });
    const normalizedSearch = search.trim().toUpperCase();
    return result.items
      .map((vehicle) => vehicle.registrationNumber)
      .filter((registrationNumber) =>
        registrationNumber.toUpperCase().includes(normalizedSearch)
      )
      .sort((first, second) => {
        const firstPrefix = first.toUpperCase().startsWith(normalizedSearch);
        const secondPrefix = second.toUpperCase().startsWith(normalizedSearch);
        return (
          Number(secondPrefix) - Number(firstPrefix) ||
          first.localeCompare(second)
        );
      });
  }
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

export function clearAdminOperationalData(confirmation) {
  return apiRequest('/api/admin/operational-data/clear', {
    method: 'POST',
    body: JSON.stringify({ confirmation })
  });
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

export function startMeterPhotoSession(vehicleId = null) {
  return apiRequest('/api/meter-photos/sessions', {
    method: 'POST',
    ...(vehicleId != null
      ? { body: JSON.stringify({ vehicle_id: vehicleId }) }
      : {})
  });
}

export function uploadMeterPhoto(
  sessionToken,
  photo,
  readingMode = 'ocr',
  onProgress = () => {}
) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    const path = '/api/meter-photos';
    const body = new FormData();
    body.append('session_token', sessionToken);
    body.append('photo', photo);
    body.append('reading_mode', readingMode);

    request.open('POST', apiUrl(path));
    request.withCredentials = true;
    request.timeout = 120000;
    request.setRequestHeader('Accept', 'application/json');
    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });
    request.addEventListener('load', () => {
      let result = null;
      if (request.responseText) {
        try {
          result = JSON.parse(request.responseText);
        } catch (error) {
          if (request.status >= 200 && request.status < 300) {
            reject(error);
            return;
          }
        }
      }
      if (request.status >= 200 && request.status < 300) {
        resolve(result);
        return;
      }
      const requestError = new Error(
        formatErrorDetail(result?.detail) ||
          `Request failed (${request.status})`
      );
      requestError.status = request.status;
      requestError.path = path;
      reject(requestError);
    });
    request.addEventListener('error', () => {
      reject(new Error('Connection interrupted during upload. Check the connection and retry.'));
    });
    request.addEventListener('timeout', () => {
      reject(new Error('Photo upload timed out. Check the connection and retry.'));
    });
    request.send(body);
  });
}

export function recognizeMeterPhoto(meterPhotoId, processingPhoto = null) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 30000);
  const options = {
    method: 'POST',
    signal: controller.signal
  };
  if (processingPhoto) {
    const body = new FormData();
    body.append('processing_photo', processingPhoto);
    options.body = body;
  }
  return apiRequest(`/api/meter-photos/${meterPhotoId}/recognize`, {
    ...options
  }).catch((requestError) => {
    if (controller.signal.aborted) {
      throw new Error(
        'Reading is taking longer than expected. The photo is saved; retry safely.'
      );
    }
    throw requestError;
  }).finally(() => {
    window.clearTimeout(timeoutId);
  });
}

export function verifyMeterPhoto(meterPhotoId, readings) {
  return apiRequest(`/api/meter-photos/${meterPhotoId}/verify`, {
    method: 'PATCH',
    body: JSON.stringify(readings)
  });
}

export function getMeterPhotoPolicy() {
  return apiRequest('/api/meter-photos/policy');
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

export function getAdminMeterReadingReviews() {
  return apiRequest('/api/admin/meter-reading-reviews');
}

export function decideAdminMeterReadingReview(reviewId, decision, note) {
  return apiRequest(`/api/admin/meter-reading-reviews/${reviewId}/decision`, {
    method: 'POST',
    body: JSON.stringify({ decision, note })
  });
}
