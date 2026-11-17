import { useCallback, useEffect, useMemo, useState } from 'react';
import companyLogo from '../../brusna-curious-cat-logo.png';
import {
  getExecutiveAnalytics,
  getExecutiveDashboard,
  getExecutiveEmployeeFuelRecords,
  getExecutiveEmployees,
  getExecutiveVehicle,
  getExecutiveVehicles,
  getMyVehicle,
  setMyVehicle
} from './api/client.js';
import { formatMileage } from './utils/distance.js';
import './boss-dashboard.css';

const RANGE_OPTIONS = [7, 30, 90];
const READ_NOTIFICATIONS_KEY = 'diesel-desk-executive-read-notifications';

function formatDashboardError(error) {
  const message =
    typeof error?.message === 'string'
      ? error.message
      : 'Unexpected dashboard request error.';
  return error?.path ? `${error.path}: ${message}` : message;
}

function formatNumber(value, digits = 0) {
  return value == null
    ? '—'
    : new Intl.NumberFormat('en-IE', {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits
      }).format(value);
}

function formatEuro(value) {
  return value == null
    ? '—'
    : new Intl.NumberFormat('en-IE', {
        style: 'currency',
        currency: 'EUR',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(value);
}

function formatDate(
  value,
  options = { day: 'numeric', month: 'short', year: 'numeric' }
) {
  if (!value) return '—';
  const hasTime = typeof value === 'string' && value.includes('T');
  const hasZone =
    typeof value === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/i.test(value);
  const date = new Date(hasTime && !hasZone ? `${value}Z` : value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('en-IE', options).format(date);
}

function formatDateTime(value) {
  return formatDate(value, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit'
  });
}

function formatEmployeeNames(names = []) {
  if (!names.length) return 'Unassigned';
  return names.join(', ');
}

function Icon({ name, size = 18 }) {
  const paths = {
    bell: (
      <>
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
        <path d="M10 21h4" />
      </>
    ),
    chevron: <path d="m6 9 6 6 6-6" />,
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    close: (
      <>
        <path d="m18 6-12 12M6 6l12 12" />
      </>
    ),
    fuel: (
      <>
        <path d="M12 3s-6 7.2-6 11a6 6 0 0 0 12 0C18 10.2 12 3 12 3Z" />
        <path d="M9.5 15.5a2.5 2.5 0 0 0 2.5 2.5" />
      </>
    ),
    gauge: (
      <>
        <path d="M4.6 18a9 9 0 1 1 14.8 0" />
        <path d="m12 13 4-4M3 20h18" />
      </>
    ),
    logout: (
      <>
        <path d="M10 17l5-5-5-5M15 12H3" />
        <path d="M12 3h7a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-7" />
      </>
    ),
    moon: <path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.6 8.6 0 1 0 11 11Z" />,
    refresh: (
      <>
        <path d="M20 7v5h-5M4 17v-5h5" />
        <path d="M5.5 9A7 7 0 0 1 18 6l2 6M4 12l2 6a7 7 0 0 0 12.5-3" />
      </>
    ),
    search: (
      <>
        <circle cx="10.8" cy="10.8" r="6.8" />
        <path d="m16 16 4.5 4.5" />
      </>
    ),
    sun: (
      <>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" />
      </>
    ),
    vehicle: (
      <>
        <path d="m3 11 2-5h14l2 5v8h-2v-2H5v2H3z" />
        <path d="M5 11h14M6 14h.01M18 14h.01" />
      </>
    )
  };
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name] ?? null}
    </svg>
  );
}

function KpiCard({ label, value, meta, icon, tone = 'default' }) {
  return (
    <article className={`boss-kpi-card tone-${tone}`}>
      <div className="boss-kpi-top">
        <span className="boss-kpi-icon">
          <Icon name={icon} size={17} />
        </span>
        <span>{label}</span>
                </div>
      <strong>{value}</strong>
      <small>{meta}</small>
    </article>
  );
}

function LineChart({ labels, values, rangeDays }) {
  const width = 720;
  const height = 220;
  const padding = { top: 16, right: 12, bottom: 30, left: 12 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const maxValue = Math.max(...values, 1);
  const points = values.map((value, index) => {
    const x =
      padding.left +
      (values.length < 2
        ? chartWidth / 2
        : (index / (values.length - 1)) * chartWidth);
    const y = padding.top + chartHeight - (value / maxValue) * chartHeight;
    return [x, y];
  });
  const pointList = points.map(([x, y]) => `${x},${y}`).join(' ');
  const areaPath = points.length
    ? [
        `M ${points[0][0]} ${padding.top + chartHeight}`,
        `L ${pointList.replaceAll(',', ' ')}`,
        `L ${points.at(-1)[0]} ${padding.top + chartHeight}`,
        'Z'
      ].join(' ')
    : '';
  const ticks =
    rangeDays === 7
      ? [0, 2, 4, 6]
      : [
          0,
          Math.floor((labels.length - 1) / 3),
          Math.floor(((labels.length - 1) * 2) / 3),
          labels.length - 1
        ];

  return (
    <div className="boss-chart-wrap">
      {values.every((value) => value === 0) ? (
        <div className="boss-chart-empty">No diesel fills recorded in this period.</div>
      ) : (
        <svg
          className="boss-line-chart"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Daily diesel consumption in litres"
        >
          {[0, 0.5, 1].map((fraction) => {
            const y = padding.top + chartHeight * fraction;
            return (
              <line
                key={fraction}
                x1={padding.left}
                x2={width - padding.right}
                y1={y}
                y2={y}
                className="boss-chart-gridline"
              />
            );
          })}
          <path d={areaPath} className="boss-chart-area" />
          <polyline points={pointList} className="boss-chart-line" />
          {points.map(([x, y], index) => (
            <circle
              key={labels[index]}
              cx={x}
              cy={y}
              r="2.8"
              className="boss-chart-point"
            >
              <title>
                {`${formatDate(labels[index], {
                  day: 'numeric',
                  month: 'short'
                })}: ${formatNumber(values[index], 1)} L`}
              </title>
            </circle>
          ))}
          {ticks.map(
            (index) =>
              labels[index] && (
                <text
                  key={labels[index]}
                  x={points[index]?.[0]}
                  y={height - 7}
                  textAnchor="middle"
                  className="boss-chart-label"
                >
                  {formatDate(labels[index], {
                    day: 'numeric',
                    month: 'short'
                  })}
                </text>
              )
          )}
        </svg>
      )}
    </div>
  );
}

function BarChart({ labels, values }) {
  const width = 720;
  const height = 220;
  const padding = { top: 16, right: 12, bottom: 30, left: 12 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const maxValue = Math.max(...values, 1);
  const slot = chartWidth / Math.max(values.length, 1);
  const barWidth = Math.max(2, Math.min(20, slot * 0.58));
  const ticks =
    values.length <= 7
      ? values.map((_, index) => index)
      : [
          0,
          Math.floor((labels.length - 1) / 3),
          Math.floor(((labels.length - 1) * 2) / 3),
          labels.length - 1
        ];

  return (
    <div className="boss-chart-wrap">
      {values.every((value) => value === 0) ? (
        <div className="boss-chart-empty">No fuel costs are recorded for this period.</div>
      ) : (
        <svg
          className="boss-bar-chart"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Daily recorded fuel costs in euro"
        >
          {[0, 0.5, 1].map((fraction) => {
            const y = padding.top + chartHeight * fraction;
            return (
              <line
                key={fraction}
                x1={padding.left}
                x2={width - padding.right}
                y1={y}
                y2={y}
                className="boss-chart-gridline"
              />
            );
          })}
          {values.map((value, index) => {
            const barHeight = (value / maxValue) * chartHeight;
            const x = padding.left + index * slot + (slot - barWidth) / 2;
            const y = padding.top + chartHeight - barHeight;
            return (
              <rect
                key={labels[index]}
                x={x}
                y={y}
                width={barWidth}
                height={barHeight}
                rx="3"
                className="boss-chart-bar"
              >
                <title>
                  {`${formatDate(labels[index], {
                    day: 'numeric',
                    month: 'short'
                  })}: ${formatEuro(value)}`}
                </title>
              </rect>
            );
          })}
          {ticks.map(
            (index) =>
              labels[index] && (
                <text
                  key={labels[index]}
                  x={padding.left + index * slot + slot / 2}
                  y={height - 7}
                  textAnchor="middle"
                  className="boss-chart-label"
                >
                  {formatDate(labels[index], {
                    day: 'numeric',
                    month: 'short'
                  })}
                </text>
              )
          )}
        </svg>
      )}
    </div>
  );
}

export default function BossDashboard({
  employee,
  theme,
  onLogout,
  onNotify,
  onToggleTheme,
  onBackToWorkspace,
  onFuelRecordCreated,
  renderFuelEntry,
  embedded = false
}) {
  const [activeView, setActiveView] = useState('summary');
  const [overview, setOverview] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [myVehicleData, setMyVehicleData] = useState(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [rangeDays, setRangeDays] = useState(30);
  const [clock, setClock] = useState(() => new Date());
  const [tableFilters, setTableFilters] = useState({
    page: 1,
    page_size: 10,
    status: 'all',
    nct: 'all',
    sort_by: 'activity',
    sort_order: 'desc'
  });
  const [searchText, setSearchText] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [vehiclePage, setVehiclePage] = useState(null);
  const [vehicleLoading, setVehicleLoading] = useState(false);
  const [vehicleError, setVehicleError] = useState('');
  const [selectedVehicleId, setSelectedVehicleId] = useState(null);
  const [vehicleDetail, setVehicleDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [personalSelection, setPersonalSelection] = useState('');
  const [personalSaving, setPersonalSaving] = useState(false);
  const [personalError, setPersonalError] = useState('');
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [employeeRefreshKey, setEmployeeRefreshKey] = useState(0);
  const readNotificationsKey = `${READ_NOTIFICATIONS_KEY}-${employee.id}`;
  const [readNotificationIds, setReadNotificationIds] = useState(() => {
    const value = window.localStorage.getItem(readNotificationsKey);
    if (!value) return [];
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed.filter((id) => typeof id === 'string') : [];
    } catch {
      return [];
    }
  });

  const loadOverview = useCallback(async () => {
    setError('');
    setRefreshing(true);
    setPersonalError('');
    const [overviewResult, personalResult] = await Promise.allSettled([
      getExecutiveDashboard(),
      getMyVehicle()
    ]);
    if (overviewResult.status === 'fulfilled') {
      setOverview(overviewResult.value);
    } else {
      setError(formatDashboardError(overviewResult.reason));
    }
    if (personalResult.status === 'fulfilled') {
      setMyVehicleData(personalResult.value);
      setPersonalSelection(
        personalResult.value.vehicle
          ? String(personalResult.value.vehicle.id)
          : ''
      );
    } else {
      setPersonalError(personalResult.reason.message);
    }
    setInitialLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    loadOverview();
    const intervalId = window.setInterval(() => setClock(new Date()), 30_000);
    return () => window.clearInterval(intervalId);
  }, [loadOverview]);

  useEffect(() => {
    let active = true;
    getExecutiveAnalytics(rangeDays)
      .then((result) => {
        if (active) setAnalytics(result);
      })
      .catch((requestError) => {
        if (active) setError(formatDashboardError(requestError));
      });
    return () => {
      active = false;
    };
  }, [rangeDays]);

  useEffect(() => {
    const timeoutId = window.setTimeout(
      () => setDebouncedSearch(searchText.trim()),
      250
    );
    return () => window.clearTimeout(timeoutId);
  }, [searchText]);

  useEffect(() => {
    let active = true;
    setVehicleLoading(true);
    setVehicleError('');
    getExecutiveVehicles({
      ...tableFilters,
      search: debouncedSearch
    })
      .then((result) => {
        if (active) setVehiclePage(result);
      })
      .catch((requestError) => {
        if (active) setVehicleError(requestError.message);
      })
      .finally(() => {
        if (active) setVehicleLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tableFilters, debouncedSearch]);

  useEffect(() => {
    window.localStorage.setItem(
      readNotificationsKey,
      JSON.stringify(readNotificationIds)
    );
  }, [readNotificationsKey, readNotificationIds]);

  useEffect(() => {
    if (selectedVehicleId == null) {
      setVehicleDetail(null);
      return undefined;
    }
    let active = true;
    setDetailLoading(true);
    setDetailError('');
    getExecutiveVehicle(selectedVehicleId)
      .then((result) => {
        if (active) setVehicleDetail(result);
      })
      .catch((requestError) => {
        if (active) setDetailError(requestError.message);
      })
      .finally(() => {
        if (active) setDetailLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedVehicleId]);

  const notifications = overview?.notifications ?? [];
  const unreadCount = notifications.filter(
    (item) => !readNotificationIds.includes(item.id)
  ).length;
  const personalOptions = useMemo(() => {
    const options = [...(myVehicleData?.availableVehicles ?? [])];
    if (
      myVehicleData?.vehicle &&
      !options.some((vehicle) => vehicle.id === myVehicleData.vehicle.id)
    ) {
      options.unshift(myVehicleData.vehicle);
    }
    return options;
  }, [myVehicleData]);

  function updateTableFilter(key, value) {
    setTableFilters((current) => ({ ...current, [key]: value, page: 1 }));
  }

  function toggleSort(field) {
    setTableFilters((current) => ({
      ...current,
      page: 1,
      sort_by: field,
      sort_order:
        current.sort_by === field && current.sort_order === 'asc'
          ? 'desc'
          : 'asc'
    }));
  }

  async function handleSavePersonalVehicle(event) {
    event.preventDefault();
    setPersonalError('');
    setPersonalSaving(true);
    try {
      const updated = await setMyVehicle(
        personalSelection ? Number(personalSelection) : null
      );
      setMyVehicleData(updated);
      setPersonalSelection(updated.vehicle ? String(updated.vehicle.id) : '');
      onNotify(
        updated.vehicle
          ? `${updated.vehicle.registrationNumber} saved as your personal vehicle.`
          : 'Personal vehicle assignment removed.'
      );
    } catch (requestError) {
      setPersonalError(requestError.message);
    } finally {
      setPersonalSaving(false);
    }
  }

  function openNotification(notification) {
    setReadNotificationIds((current) =>
      current.includes(notification.id) ? current : [...current, notification.id]
    );
    setNotificationsOpen(false);
    if (notification.vehicleId != null) {
      setSelectedVehicleId(notification.vehicleId);
      document.getElementById('bossFleet')?.scrollIntoView({ behavior: 'smooth' });
    } else if (notification.kind === 'nct') {
      document.getElementById('bossNct')?.scrollIntoView({ behavior: 'smooth' });
    }
  }

  function switchDashboardView(view) {
    if (view === activeView) return;
    setActiveView(view);
    window.requestAnimationFrame(() => {
      document.getElementById('bossOverview')?.scrollIntoView({
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
          ? 'auto'
          : 'smooth',
        block: 'start'
      });
    });
  }

  async function refreshAll() {
    setEmployeeRefreshKey((current) => current + 1);
    await Promise.all([
      loadOverview(),
      getExecutiveAnalytics(rangeDays)
        .then(setAnalytics)
        .catch((requestError) =>
          setError(formatDashboardError(requestError))
        ),
      getExecutiveVehicles({ ...tableFilters, search: debouncedSearch })
        .then(setVehiclePage)
        .catch((requestError) => setVehicleError(requestError.message))
    ]);
  }

  async function handleFuelRecordCreated(record) {
    await onFuelRecordCreated(record);
    await refreshAll();
  }

  const meter = overview?.meter;
  const nct = overview?.nct;
  const todaySummary = overview?.todaySummary;
  const monthSummary = overview?.monthSummary;
  const nctAttentionCount = (nct?.expiringCount ?? 0) + (nct?.expiredCount ?? 0);
  const readingsToReview =
    (meter?.reviewCount ?? 0) + (meter?.lowConfidenceCount ?? 0);
  const currentVehicle = myVehicleData?.vehicle;
  const analyticsDieselTotal =
    analytics?.dieselLitres.reduce((sum, value) => sum + value, 0) ?? 0;
  const analyticsFuelCost =
    analytics?.fuelCostEur.reduce((sum, value) => sum + value, 0) ?? 0;
  const analyticsCostRecordCount =
    analytics?.costRecordCount.reduce((sum, value) => sum + value, 0) ?? 0;
  const unreadLabel = unreadCount
    ? `${unreadCount} unread notification${unreadCount === 1 ? '' : 's'}`
    : 'No unread notifications';
  const DashboardRoot = embedded ? 'section' : 'main';

  return (
    <DashboardRoot
      className={`boss-dashboard${embedded ? ' boss-dashboard-embedded' : ''}`}
      id="bossOverview"
    >
      <header className="boss-header">
        <div className="boss-brand">
          {onBackToWorkspace && (
            <button
              className="boss-back-button"
              type="button"
              onClick={onBackToWorkspace}
            >
              Admin workspace
            </button>
          )}
          <img src={companyLogo} alt="Brusna, the retrofit specialists" />
          <div className="boss-brand-copy">
            <span>FLEET INTELLIGENCE</span>
            <strong>{embedded ? 'Fleet summary' : 'Executive dashboard'}</strong>
          </div>
        </div>
        {renderFuelEntry && (
          <div className="boss-dashboard-tabs" role="tablist" aria-label="Boss dashboard">
            <button
              id="bossSummaryTab"
              type="button"
              role="tab"
              aria-selected={activeView === 'summary'}
              aria-controls="bossSummaryPanel"
              className={activeView === 'summary' ? 'active' : ''}
              onClick={() => switchDashboardView('summary')}
            >
              Fleet summary
            </button>
            <button
              id="bossFuelTab"
              type="button"
              role="tab"
              aria-selected={activeView === 'fuel'}
              aria-controls="bossFuelPanel"
              className={activeView === 'fuel' ? 'active' : ''}
              onClick={() => switchDashboardView('fuel')}
            >
              New fill
            </button>
          </div>
        )}
        {activeView === 'summary' && (
          <nav className="boss-header-nav" aria-label="Dashboard sections">
            <a href="#bossOverview">Overview</a>
            <a href="#bossAnalytics">Analytics</a>
            <a href="#bossFleet">Fleet</a>
            <a href="#bossEmployees">Employees</a>
          </nav>
        )}
        <div className="boss-header-actions">
          <div className="boss-clock">
            <Icon name="clock" size={15} />
            <span>
              {formatDate(clock, {
                weekday: 'short',
                day: 'numeric',
                month: 'short'
              })}
            </span>
          </div>
          <button
            className="boss-icon-button boss-theme-button"
            type="button"
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            aria-pressed={theme === 'dark'}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            onClick={onToggleTheme}
          >
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
          </button>
          <div className="boss-popover-anchor">
            <button
              className="boss-icon-button"
              type="button"
              aria-label={unreadLabel}
              aria-expanded={notificationsOpen}
              onClick={() => {
                setNotificationsOpen((open) => !open);
                setProfileOpen(false);
              }}
            >
              <Icon name="bell" />
              {unreadCount > 0 && (
                <span className="boss-notification-badge">
                  {unreadCount > 9 ? '9+' : unreadCount}
                </span>
              )}
            </button>
            {notificationsOpen && (
              <section
                className="boss-popover boss-notification-popover"
                role="dialog"
                aria-label="Notifications"
              >
                <div className="boss-popover-heading">
                  <div>
                    <span className="boss-overline">ACTIVITY</span>
                    <h2>Notifications</h2>
                  </div>
                  <button
                    className="boss-small-icon-button"
                    type="button"
                    aria-label="Close notifications"
                    onClick={() => setNotificationsOpen(false)}
                  >
                    <Icon name="close" size={15} />
                  </button>
                </div>
                {notifications.length ? (
                  <ul className="boss-notification-list">
                    {notifications.map((item) => (
                      <li key={item.id}>
                        <button
                          type="button"
                          className={`boss-notification-item severity-${item.severity}`}
                          onClick={() => openNotification(item)}
                        >
                          <span className="boss-notification-dot" />
                          <span>
                            <strong>{item.title}</strong>
                            <small>{item.description}</small>
                          </span>
                          {!readNotificationIds.includes(item.id) && (
                            <span className="boss-unread-indicator" />
                          )}
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="boss-popover-empty">No new fleet alerts.</p>
                )}
              </section>
            )}
          </div>
          <div className="boss-popover-anchor">
            <button
              className="boss-profile-button"
              type="button"
              aria-expanded={profileOpen}
              onClick={() => {
                setProfileOpen((open) => !open);
                setNotificationsOpen(false);
              }}
            >
              <span className="boss-avatar">
                {employee.name?.slice(0, 1).toUpperCase() ?? 'B'}
              </span>
              <span className="boss-profile-copy">
                <strong>{employee.name}</strong>
                <small>
                  {employee.role === 'admin' ? 'Administrator' : 'Boss'}
                </small>
              </span>
              <Icon name="chevron" size={14} />
            </button>
            {profileOpen && (
              <div className="boss-popover boss-profile-popover" role="menu">
                <div className="boss-profile-menu-identity">
                  <strong>{employee.name}</strong>
                  <small>{employee.email}</small>
                </div>
                <button
                  type="button"
                  role="menuitem"
                  onClick={onLogout}
                >
                  <Icon name="logout" size={16} />
                  Sign out
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div
        className={`boss-content${
          renderFuelEntry ? ` boss-content-${activeView}` : ''
        }`}
        id={
          renderFuelEntry && activeView === 'fuel'
            ? 'bossFuelPanel'
            : 'bossSummaryPanel'
        }
        role={renderFuelEntry ? 'tabpanel' : undefined}
        aria-labelledby={
          renderFuelEntry
            ? activeView === 'fuel'
              ? 'bossFuelTab'
              : 'bossSummaryTab'
            : undefined
        }
      >
        {renderFuelEntry && activeView === 'fuel' ? (
          <section className="boss-fuel-panel" tabIndex={0}>
            {renderFuelEntry(handleFuelRecordCreated)}
          </section>
        ) : (
          <>
        <section className="boss-welcome">
          <div>
            <p className="boss-overline">
              FLEET OVERVIEW <span className="boss-live-dot" /> LIVE
            </p>
            <h1>
              Good{' '}
              {clock.getHours() < 12
                ? 'morning'
                : clock.getHours() < 18
                  ? 'afternoon'
                  : 'evening'}
              , {employee.name.split(' ')[0]}.
            </h1>
            <p>
              Company fleet performance at a glance. Personal vehicles stay
              separate from company totals.
            </p>
          </div>
          <button
            className="boss-refresh-button"
            type="button"
            onClick={refreshAll}
            disabled={refreshing}
          >
            <Icon name="refresh" size={15} />
            {refreshing ? 'Refreshing…' : 'Refresh data'}
          </button>
        </section>

        {error && (
          <div className="boss-error-banner" role="alert">
            <span>
              <strong>Dashboard data could not be loaded.</strong> {error}
            </span>
            <button type="button" onClick={refreshAll}>
              Try again
            </button>
          </div>
        )}

        {initialLoading ? (
          <div className="boss-loading" role="status">
            <span className="boss-spinner" />
            Loading verified fleet data…
          </div>
        ) : overview ? (
          <>
            <section
              className="boss-kpi-grid"
              aria-label="Fleet key performance indicators"
            >
              <KpiCard
                label="Company vehicles"
                value={formatNumber(overview.fleet.totalVehicles)}
                meta={`${formatNumber(overview.fleet.activeVehicles)} active · ${formatNumber(overview.fleet.inactiveVehicles)} inactive`}
                icon="vehicle"
              />
              <KpiCard
                label="Diesel today"
                value={`${formatNumber(todaySummary.litres, 1)} L`}
                meta={`${formatNumber(todaySummary.transactionCount)} fuel record${todaySummary.transactionCount === 1 ? '' : 's'} today`}
                icon="fuel"
                tone="green"
              />
              <KpiCard
                label="Recorded fuel spend"
                value={
                  monthSummary.costRecordCount
                    ? formatEuro(monthSummary.costEur)
                    : '—'
                }
                meta={
                  monthSummary.costRecordCount
                    ? `This month · ${formatNumber(monthSummary.costRecordCount)} priced records`
                    : 'No costs recorded this month'
                }
                icon="gauge"
                tone="blue"
              />
              <KpiCard
                label="Global meter"
                value={
                  meter?.currentTotalInteger != null
                    ? `${formatNumber(meter.currentTotalInteger / 1000, 3)} L`
                    : meter?.currentCumulativeTotalLitres == null
                      ? '—'
                      : `${formatNumber(meter.currentCumulativeTotalLitres, 1)} L`
                }
                meta={
                  meter?.lastUpdatedAt
                    ? `${meter.isDemo ? 'Sample data · ' : ''}Updated ${
                        formatDateTime(meter.lastUpdatedAt)
                      }`
                    : 'No verified company reading'
                }
                icon="gauge"
              />
              <KpiCard
                label="NCT attention"
                value={formatNumber(nctAttentionCount)}
                meta={`${formatNumber(nct?.missingDateCount ?? 0)} without a date`}
                icon="clock"
                tone={nct?.expiredCount ? 'red' : 'amber'}
              />
              <KpiCard
                label="Readings to review"
                value={formatNumber(readingsToReview)}
                meta={`${formatNumber(
                  meter?.reviewCount ?? 0
                )} discrepancies · ${formatNumber(
                  meter?.lowConfidenceCount ?? 0
                )} low-confidence photos`}
                icon="bell"
                tone={readingsToReview ? 'amber' : 'default'}
              />
            </section>

            {monthSummary.missingCostCount > 0 && (
              <div className="boss-data-notice" role="status">
                <span className="boss-notice-mark">!</span>
                <p>
                  <strong>Fuel costs are incomplete.</strong>{' '}
                  {formatNumber(monthSummary.missingCostCount)} record(s) this
                  month have no recorded cost; spend totals include only
                  recorded costs.
                </p>
                <span className="boss-notice-unit">EUR</span>
              </div>
            )}

            <section className="boss-main-grid">
              <section className="boss-panel boss-nct-panel" id="bossNct">
                <div className="boss-panel-heading">
                  <div className="boss-nct-heading-copy">
                    <h2>NCT status</h2>
                    <p>Expiry dates for your company vehicles</p>
                  </div>
                </div>
                <div
                  className="boss-nct-stats"
                  role="group"
                  aria-label="NCT summary"
                >
                  <div className="boss-nct-stat status-valid">
                    <strong>{formatNumber(nct?.validCount)}</strong>
                    <span>In date</span>
                  </div>
                  <div className="boss-nct-stat status-upcoming">
                    <strong>{formatNumber(nct?.expiringCount)}</strong>
                    <span>Due soon</span>
                  </div>
                  <div className="boss-nct-stat status-expired">
                    <strong>{formatNumber(nct?.expiredCount)}</strong>
                    <span>Overdue</span>
                  </div>
                  <div className="boss-nct-stat status-not_set">
                    <strong>{formatNumber(nct?.missingDateCount)}</strong>
                    <span>No expiry date</span>
                  </div>
                </div>
                {nct?.alerts.length ? (
                  <ul
                    className="boss-nct-list"
                    aria-label="Vehicles with upcoming or overdue NCT dates"
                  >
                    {nct.alerts.slice(0, 5).map((alert) => {
                      const statusLabel =
                        alert.status === 'expired'
                          ? 'Overdue'
                          : alert.daysRemaining === 0
                            ? 'Due today'
                            : `Due in ${formatNumber(alert.daysRemaining)} ${
                                alert.daysRemaining === 1 ? 'day' : 'days'
                              }`;

                      return (
                        <li key={alert.vehicleId}>
                          <button
                            type="button"
                            aria-label={`View NCT details for ${alert.registrationNumber}`}
                            onClick={() =>
                              setSelectedVehicleId(alert.vehicleId)
                            }
                          >
                            <span
                              className={`boss-nct-status status-${alert.status}`}
                            >
                              {statusLabel}
                            </span>
                            <span className="boss-nct-vehicle">
                              <strong>{alert.registrationNumber}</strong>
                              <small>
                                {formatEmployeeNames(alert.employeeNames)}
                              </small>
                            </span>
                            <span className="boss-nct-expiry">
                              <small>NCT expiry</small>
                              <time>{formatDate(alert.nctExpiryDate)}</time>
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="boss-nct-empty">
                    No vehicles have upcoming or overdue NCT dates.
                  </p>
                )}
                {nct?.missingDateCount > 0 && (
                  <p className="boss-panel-footnote">
                    {formatNumber(nct.missingDateCount)} vehicles have no NCT
                    expiry date recorded.
                  </p>
                )}
              </section>
              <section
                className="boss-panel boss-analytics-panel"
                id="bossAnalytics"
              >
                <div className="boss-panel-heading boss-analytics-heading">
                  <div>
                    <p className="boss-overline">FLEET ANALYTICS</p>
                    <h2>Fuel performance</h2>
                    <p>Daily company-vehicle activity from verified records.</p>
                  </div>
                  <div
                    className="boss-range-switch"
                    role="group"
                    aria-label="Analytics date range"
                  >
                    {RANGE_OPTIONS.map((days) => (
                      <button
                        key={days}
                        type="button"
                        className={rangeDays === days ? 'active' : ''}
                        aria-pressed={rangeDays === days}
                        onClick={() => setRangeDays(days)}
                      >
                        {days} days
                      </button>
                    ))}
                  </div>
                </div>
                <div className="boss-chart-grid">
                  <article className="boss-chart-card">
                    <div className="boss-chart-heading">
                      <div>
                        <h3>Diesel consumption</h3>
                        <span>
                          Litres ·{' '}
                          {analytics
                            ? `${formatDate(analytics.startDate)} – ${formatDate(analytics.endDate)}`
                            : 'Loading'}
                        </span>
                      </div>
                      <strong>
                        {formatNumber(analyticsDieselTotal, 1)} <small>L</small>
                      </strong>
                    </div>
                    <LineChart
                      labels={analytics?.labels ?? []}
                      values={analytics?.dieselLitres ?? []}
                      rangeDays={rangeDays}
                    />
                  </article>
                  <article className="boss-chart-card">
                    <div className="boss-chart-heading">
                      <div>
                        <h3>Recorded fuel spend</h3>
                        <span>EUR · missing prices excluded</span>
                      </div>
                      <strong>
                        {analyticsCostRecordCount
                          ? formatEuro(analyticsFuelCost)
                          : '—'}
                      </strong>
                    </div>
                    <BarChart
                      labels={analytics?.labels ?? []}
                      values={analytics?.fuelCostEur ?? []}
                    />
                    {analytics && analyticsCostRecordCount === 0 && (
                      <p className="boss-chart-caption">
                        No costs recorded for the selected period.
                      </p>
                    )}
                  </article>
                </div>
                <div className="boss-usage-comparison">
                  <div className="boss-comparison-title">
                    <span className="boss-overline">DIESEL BY VEHICLE</span>
                    <small>Based on recorded fills in this period</small>
                  </div>
                  <div className="boss-comparison-columns">
                    <VehicleUsageList title="Highest recorded usage" vehicles={analytics?.topVehicles ?? []} />
                    <VehicleUsageList title="Lowest recorded usage" vehicles={analytics?.lowestVehicles ?? []} />
                  </div>
                </div>
              </section>

            <section
              className="boss-personal-panel boss-panel"
              aria-labelledby="bossPersonalVehicleTitle"
            >
              <div className="boss-personal-intro">
                <span className="boss-personal-icon">
                  <Icon name="vehicle" size={20} />
                </span>
                <div className="boss-personal-heading-copy">
                  <div className="boss-personal-heading-row">
                    <p className="boss-overline">PERSONAL VEHICLE</p>
                    <span className="boss-personal-separation">
                      Separate from fleet totals
                    </span>
                  </div>
                  <h2 id="bossPersonalVehicleTitle">My vehicle</h2>
                  <p>
                    This personal selection stays outside company fleet totals
                    and does not change your assigned work vehicle.
                  </p>
                </div>
              </div>
              <div className="boss-personal-content">
                <div className="boss-personal-summary">
                  {currentVehicle ? (
                    <>
                      <strong>{currentVehicle.registrationNumber}</strong>
                      <span>
                        {[currentVehicle.make, currentVehicle.model]
                          .filter(Boolean)
                          .join(' ') || 'Vehicle details not listed'}
                      </span>
                      <small>
                        {currentVehicle.latestMileageMiles == null
                          ? 'No mileage record'
                          : `${formatMileage(currentVehicle.latestMileageMiles)} mi latest mileage`}
                      </small>
                      <div className="boss-personal-stats">
                        <span>
                          <small>Diesel this month</small>
                          <strong>
                            {formatNumber(currentVehicle.monthDieselLitres, 1)} L
                          </strong>
                        </span>
                        <span>
                          <small>Recorded cost</small>
                          <strong>
                            {currentVehicle.monthCostRecordCount
                              ? formatEuro(currentVehicle.monthCostEur)
                              : '—'}
                          </strong>
                        </span>
                      </div>
                    </>
                  ) : (
                    <div className="boss-personal-empty">
                      <strong>No personal vehicle selected</strong>
                      <span>
                        Choose a vehicle here to track it separately from your
                        company vehicle.
                      </span>
                    </div>
                  )}
                </div>
                <form
                  className="boss-personal-form"
                  onSubmit={handleSavePersonalVehicle}
                >
                  <label htmlFor="bossPersonalVehicle">
                    Your personal vehicle
                  </label>
                  <select
                    id="bossPersonalVehicle"
                    value={personalSelection}
                    onChange={(event) =>
                      setPersonalSelection(event.target.value)
                    }
                    disabled={!personalOptions.length}
                  >
                    <option value="">
                      {personalOptions.length
                        ? 'No personal vehicle selected'
                        : 'No personal vehicles available'}
                    </option>
                    {personalOptions.map((vehicle) => (
                      <option key={vehicle.id} value={vehicle.id}>
                        {vehicle.registrationNumber} ·{' '}
                        {[vehicle.make, vehicle.model]
                          .filter(Boolean)
                          .join(' ') || 'Vehicle details not listed'}
                      </option>
                    ))}
                  </select>
                  {personalError && (
                    <p className="boss-form-error" role="alert">
                      {personalError}
                    </p>
                  )}
                  {!personalOptions.length && (
                    <p className="boss-personal-form-hint">
                      Ask an administrator to register a personal vehicle
                      before assigning it here.
                    </p>
                  )}
                  <button
                    type="submit"
                    className="boss-primary-button"
                    disabled={
                      personalSaving || (!personalSelection && !currentVehicle)
                    }
                  >
                    {personalSaving
                      ? 'Saving…'
                      : personalSelection
                        ? 'Save personal vehicle'
                        : currentVehicle
                          ? 'Remove personal vehicle'
                          : 'Save selection'}
                  </button>
                </form>
              </div>
              <div className="boss-personal-car-scene" aria-hidden="true">
                <span className="boss-personal-horizon" />
                <span className="boss-personal-road" />
                <span className="boss-personal-road-mark" />
                <svg
                  className="boss-personal-car"
                  viewBox="0 0 180 76"
                  focusable="false"
                >
                  <path
                    className="boss-personal-car-shadow"
                    d="M25 62c19-7 111-8 132 0v5H25z"
                  />
                  <path
                    className="boss-personal-car-body"
                    d="M18 51h15l10-18c3-6 9-9 16-9h46c9 0 16 4 22 11l12 16 16 3c4 1 7 4 7 8v5H18v-9c0-4 0-6 0-7Z"
                  />
                  <path
                    className="boss-personal-car-window"
                    d="m49 39 5-9c2-3 5-5 9-5h21v15H47zm40-14h16c7 0 12 3 17 9l5 6H89z"
                  />
                  <path
                    className="boss-personal-car-trim"
                    d="M19 53h21m83 0h37M85 27v14"
                  />
                  <path
                    className="boss-personal-car-light"
                    d="m153 48 7 2v4h-8M25 49h-5v5h5"
                  />
                  <g className="boss-personal-car-wheel">
                    <circle cx="51" cy="61" r="10" />
                    <path d="M51 54v14m-7-7h14m-12-5 10 10m0-10L46 66" />
                  </g>
                  <g className="boss-personal-car-wheel">
                    <circle cx="137" cy="61" r="10" />
                    <path d="M137 54v14m-7-7h14m-12-5 10 10m0-10-10 10" />
                  </g>
                </svg>
              </div>
              {currentVehicle?.transactions?.length > 0 && (
                <div className="boss-personal-history">
                  <h3>Recent personal vehicle fuel history</h3>
                  <TransactionList
                    transactions={currentVehicle.transactions.slice(0, 4)}
                  />
                </div>
              )}
            </section>
            </section>

            <section className="boss-fleet-section" id="bossFleet">
              <div className="boss-section-title">
                <div>
                  <p className="boss-overline">COMPANY VEHICLES</p>
                  <h2>Fleet registry</h2>
                  <p>
                    Search, filter, and inspect registered company vehicles.
                  </p>
                </div>
                <span className="boss-fleet-count">
                  {formatNumber(vehiclePage?.total ?? 0)} vehicles
                </span>
              </div>
              <div
                className="boss-fleet-toolbar"
                role="search"
                aria-label="Search and filter company vehicles"
              >
                <div className="boss-fleet-search">
                  <label htmlFor="bossFleetSearch">Search fleet</label>
                  <div className="boss-search boss-fleet-search-control">
                    <Icon name="search" size={17} />
                    <input
                      id="bossFleetSearch"
                      value={searchText}
                      onChange={(event) => {
                        setSearchText(event.target.value);
                        setTableFilters((current) => ({
                          ...current,
                          page: 1
                        }));
                      }}
                      placeholder="Registration, make, or model"
                      aria-label="Search company vehicles"
                    />
                    {searchText && (
                      <button
                        className="boss-search-clear"
                        type="button"
                        aria-label="Clear fleet search"
                        onClick={() => {
                          setSearchText('');
                          setTableFilters((current) => ({
                            ...current,
                            page: 1
                          }));
                        }}
                      >
                        <Icon name="close" size={14} />
                      </button>
                    )}
                  </div>
                </div>
                <label className="boss-filter">
                  <span>Status</span>
                  <select
                    value={tableFilters.status}
                    onChange={(event) =>
                      updateTableFilter('status', event.target.value)
                    }
                  >
                    <option value="all">All statuses</option>
                    <option value="active">Active</option>
                    <option value="inactive">Inactive</option>
                  </select>
                </label>
                <label className="boss-filter">
                  <span>NCT</span>
                  <select
                    value={tableFilters.nct}
                    onChange={(event) =>
                      updateTableFilter('nct', event.target.value)
                    }
                  >
                    <option value="all">All NCT dates</option>
                    <option value="valid">Valid</option>
                    <option value="expiring">Expiring soon</option>
                    <option value="expired">Expired</option>
                    <option value="missing">Not recorded</option>
                  </select>
                </label>
              </div>

              {vehicleError && (
                <div className="boss-inline-error" role="alert">
                  Could not load vehicles: {vehicleError}
                </div>
              )}
              <div className="boss-table-scroll">
                <table className="boss-fleet-table">
                  <thead>
                    <tr>
                      <th>
                        <button
                          type="button"
                          onClick={() => toggleSort('registration')}
                        >
                          Vehicle
                          <SortMark
                            field="registration"
                            active={tableFilters.sort_by}
                            order={tableFilters.sort_order}
                          />
                        </button>
                      </th>
                      <th>Assigned employees</th>
                      <th>Status</th>
                      <th>
                        <button
                          type="button"
                          onClick={() => toggleSort('nct')}
                        >
                          NCT expiry
                          <SortMark
                            field="nct"
                            active={tableFilters.sort_by}
                            order={tableFilters.sort_order}
                          />
                        </button>
                      </th>
                      <th>
                        <button
                          type="button"
                          onClick={() => toggleSort('mileage')}
                        >
                          Last mileage
                          <SortMark
                            field="mileage"
                            active={tableFilters.sort_by}
                            order={tableFilters.sort_order}
                          />
                        </button>
                      </th>
                      <th>
                        <button
                          type="button"
                          onClick={() => toggleSort('activity')}
                        >
                          Last activity
                          <SortMark
                            field="activity"
                            active={tableFilters.sort_by}
                            order={tableFilters.sort_order}
                          />
                        </button>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {vehicleLoading && !vehiclePage ? (
                      <tr>
                        <td colSpan="6" className="boss-table-empty">
                          Loading company vehicles…
                        </td>
                      </tr>
                    ) : vehiclePage?.items.length ? (
                      vehiclePage.items.map((vehicle) => (
                        <tr
                          key={vehicle.id}
                          className={
                            selectedVehicleId === vehicle.id ? 'selected' : ''
                          }
                        >
                          <td>
                            <button
                              className="boss-vehicle-link"
                              type="button"
                              onClick={() =>
                                setSelectedVehicleId((id) =>
                                  id === vehicle.id ? null : vehicle.id
                                )
                              }
                            >
                              <strong>{vehicle.registrationNumber}</strong>
                              <small>
                                {[vehicle.make, vehicle.model]
                                  .filter(Boolean)
                                  .join(' ') ||
                                  vehicle.fuelType ||
                                  'Vehicle details not listed'}
                              </small>
                            </button>
                          </td>
                          <td>{formatEmployeeNames(vehicle.employeeNames)}</td>
                          <td>
                            <span
                              className={`boss-vehicle-status ${
                                vehicle.isActive ? 'active' : 'inactive'
                              }`}
                            >
                              {vehicle.isActive ? 'Active' : 'Inactive'}
                            </span>
                          </td>
                          <td>
                            <span
                              className={`boss-nct-table-status status-${vehicle.nctStatus}`}
                            >
                              {vehicle.nctExpiryDate
                                ? formatDate(vehicle.nctExpiryDate)
                                : 'Not recorded'}
                            </span>
                          </td>
                          <td>
                            {vehicle.latestMileageMiles == null
                              ? '—'
                              : `${formatMileage(vehicle.latestMileageMiles)} mi`}
                          </td>
                          <td>{formatDateTime(vehicle.latestActivityAt)}</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan="6" className="boss-table-empty">
                          {vehicleLoading
                            ? 'Loading company vehicles…'
                            : 'No company vehicles match these filters.'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              {vehiclePage && vehiclePage.total > vehiclePage.pageSize && (
                <div className="boss-pagination">
                  <span>
                    Showing{' '}
                    {formatNumber(
                      (vehiclePage.page - 1) * vehiclePage.pageSize + 1
                    )}
                    –
                    {formatNumber(
                      Math.min(
                        vehiclePage.page * vehiclePage.pageSize,
                        vehiclePage.total
                      )
                    )}{' '}
                    of {formatNumber(vehiclePage.total)}
                  </span>
                  <div>
                    <button
                      type="button"
                      disabled={vehiclePage.page <= 1}
                      onClick={() =>
                        setTableFilters((current) => ({
                          ...current,
                          page: current.page - 1
                        }))
                      }
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      disabled={
                        vehiclePage.page * vehiclePage.pageSize >=
                        vehiclePage.total
                      }
                      onClick={() =>
                        setTableFilters((current) => ({
                          ...current,
                          page: current.page + 1
                        }))
                      }
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
              {selectedVehicleId != null && (
                <section className="boss-vehicle-detail" aria-live="polite">
                  <div className="boss-detail-heading">
                    <div>
                      <p className="boss-overline">VEHICLE PROFILE</p>
                      <h3>
                        {vehicleDetail?.registrationNumber ?? 'Vehicle details'}
                      </h3>
                    </div>
                    <button
                      className="boss-small-icon-button"
                      type="button"
                      aria-label="Close vehicle details"
                      onClick={() => setSelectedVehicleId(null)}
                    >
                      <Icon name="close" size={16} />
                    </button>
                  </div>
                  {detailLoading ? (
                    <p className="boss-table-empty">
                      Loading vehicle details…
                    </p>
                  ) : detailError ? (
                    <p className="boss-form-error" role="alert">
                      {detailError}
                    </p>
                  ) : (
                    vehicleDetail && (
                      <>
                        <div className="boss-detail-grid">
                          <span>
                            <small>Make / model</small>
                            <strong>
                              {[vehicleDetail.make, vehicleDetail.model]
                                .filter(Boolean)
                                .join(' ') || 'Not recorded'}
                            </strong>
                          </span>
                          <span>
                            <small>Fuel / tank</small>
                            <strong>
                              {vehicleDetail.fuelType ?? 'Not recorded'}
                              {vehicleDetail.tankCapacity
                                ? ` · ${formatNumber(vehicleDetail.tankCapacity, 1)} L`
                                : ''}
                            </strong>
                          </span>
                          <span>
                            <small>Employees</small>
                            <strong>
                              {formatEmployeeNames(vehicleDetail.employeeNames)}
                            </strong>
                          </span>
                          <span>
                            <small>NCT</small>
                            <strong>
                              {vehicleDetail.nctExpiryDate
                                ? `${formatDate(vehicleDetail.nctExpiryDate)} · ${vehicleDetail.nctStatus.replaceAll('_', ' ')}`
                                : 'Not recorded'}
                            </strong>
                          </span>
                          <span>
                            <small>Diesel this month</small>
                            <strong>
                              {formatNumber(vehicleDetail.monthDieselLitres, 1)} L
                            </strong>
                          </span>
                          <span>
                            <small>Recorded cost this month</small>
                            <strong>
                              {vehicleDetail.monthCostRecordCount
                                ? formatEuro(vehicleDetail.monthCostEur)
                                : '—'}
                            </strong>
                          </span>
                        </div>
                        <h4>Recent fuel activity</h4>
                        {vehicleDetail.transactions.length ? (
                          <TransactionList
                            transactions={vehicleDetail.transactions}
                          />
                        ) : (
                          <p className="boss-table-empty">
                            No non-demo fuel records for this vehicle.
                          </p>
                        )}
                      </>
                    )
                  )}
                </section>
              )}
            </section>
            <EmployeeDirectory refreshKey={employeeRefreshKey} />
          </>
        ) : null}
          </>
        )}
        <footer className="boss-footer">
          <span>Diesel Desk · {embedded ? 'Fleet summary' : 'Executive view'}</span>
          <span>
            {formatDate(clock, {
              weekday: 'long',
              day: 'numeric',
              month: 'long',
              year: 'numeric'
            })}
          </span>
        </footer>
      </div>
    </DashboardRoot>
  );
}

const EMPLOYEE_DATE_PRESETS = [
  { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 90 days' },
  { value: '1y', label: 'Last year' },
  { value: '5y', label: 'Last 5 years' }
];

function dateInputValue(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function employeeDateRangeForPreset(preset) {
  const end = new Date();
  end.setHours(0, 0, 0, 0);
  const start = new Date(end);

  if (preset === '30d') {
    start.setDate(start.getDate() - 29);
  } else if (preset === '90d') {
    start.setDate(start.getDate() - 89);
  } else {
    const years = preset === '1y' ? 1 : 5;
    start.setFullYear(start.getFullYear() - years);
    if (start.getMonth() !== end.getMonth()) start.setDate(0);
  }

  return {
    startDate: dateInputValue(start),
    endDate: dateInputValue(end)
  };
}

function EmployeeDirectory({ refreshKey }) {
  const [searchText, setSearchText] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [page, setPage] = useState(1);
  const [directory, setDirectory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedEmployee, setSelectedEmployee] = useState(null);
  const [recordsPage, setRecordsPage] = useState(1);
  const [records, setRecords] = useState(null);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [recordsError, setRecordsError] = useState('');
  const [recordRange, setRecordRange] = useState(() => ({
    ...employeeDateRangeForPreset('5y'),
    preset: '5y'
  }));
  const pageSize = 10;
  const invalidDateRange =
    recordRange.startDate &&
    recordRange.endDate &&
    recordRange.startDate > recordRange.endDate;

  useEffect(() => {
    const timeoutId = window.setTimeout(
      () => setDebouncedSearch(searchText.trim()),
      250
    );
    return () => window.clearTimeout(timeoutId);
  }, [searchText]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    getExecutiveEmployees({
      page,
      page_size: pageSize,
      search: debouncedSearch
    })
      .then((result) => {
        if (active) setDirectory(result);
      })
      .catch((requestError) => {
        if (active) setError(requestError.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page, debouncedSearch, refreshKey]);

  useEffect(() => {
    if (!selectedEmployee || invalidDateRange) {
      setRecords(null);
      setRecordsLoading(false);
      return undefined;
    }
    let active = true;
    setRecords(null);
    setRecordsLoading(true);
    setRecordsError('');
    getExecutiveEmployeeFuelRecords(selectedEmployee.id, {
      page: recordsPage,
      page_size: pageSize,
      start_date: recordRange.startDate,
      end_date: recordRange.endDate
    })
      .then((result) => {
        if (active) setRecords(result);
      })
      .catch((requestError) => {
        if (active) setRecordsError(requestError.message);
      })
      .finally(() => {
        if (active) setRecordsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [
    selectedEmployee,
    recordsPage,
    recordRange.startDate,
    recordRange.endDate,
    invalidDateRange,
    refreshKey
  ]);

  const employees = directory?.items ?? [];
  const totalPages = Math.ceil((directory?.total ?? 0) / pageSize);
  const recordTotalPages = Math.ceil((records?.total ?? 0) / pageSize);
  const selectDatePreset = (preset) => {
    setRecordRange({ ...employeeDateRangeForPreset(preset), preset });
    setRecordsPage(1);
    setRecordsError('');
  };
  const updateRecordDate = (key, value) => {
    setRecordRange((current) => ({ ...current, [key]: value, preset: 'custom' }));
    setRecordsPage(1);
    setRecordsError('');
  };

  return (
    <section className="boss-employee-section" id="bossEmployees">
      <div className="boss-section-title">
        <div>
          <p className="boss-overline">PEOPLE &amp; ACTIVITY</p>
          <h2>Employee activity</h2>
          <p>
            Review each employee&apos;s assigned company vehicles and recorded
            fuel history.
          </p>
        </div>
        <span className="boss-fleet-count">
          {formatNumber(directory?.total ?? 0)} employees
        </span>
      </div>

      <div className="boss-employee-toolbar">
        <label className="boss-search">
          <Icon name="search" size={17} />
          <input
            type="search"
            value={searchText}
            onChange={(event) => {
              setSearchText(event.target.value);
              setPage(1);
            }}
            placeholder="Search employee name"
            aria-label="Search employees"
          />
        </label>
      </div>

      {error && (
        <div className="boss-inline-error" role="alert">
          Could not load employees: {error}
        </div>
      )}

      {loading && !directory ? (
        <div className="boss-loading" role="status">
          <span className="boss-spinner" />
          Loading employee activity…
        </div>
      ) : employees.length ? (
        <div className="boss-employee-grid">
          {employees.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`boss-employee-card${
                selectedEmployee?.id === item.id ? ' selected' : ''
              }`}
              aria-pressed={selectedEmployee?.id === item.id}
              onClick={() => {
                setSelectedEmployee((current) =>
                  current?.id === item.id ? null : item
                );
                setRecordsPage(1);
              }}
            >
              <span className="boss-employee-card-top">
                <span className="boss-employee-avatar" aria-hidden="true">
                  {item.name.slice(0, 1).toUpperCase()}
                </span>
                <span className="boss-employee-identity">
                  <strong>{item.name}</strong>
                  <small>
                    {formatNumber(item.recordCount)} company record
                    {item.recordCount === 1 ? '' : 's'}
                  </small>
                </span>
                <span
                  className={`boss-employee-status ${
                    item.isActive ? 'active' : 'inactive'
                  }`}
                >
                  {item.isActive ? 'Active' : 'Inactive'}
                </span>
              </span>
              <span className="boss-employee-card-vehicles">
                {item.vehicleRegistrations.length
                  ? item.vehicleRegistrations.join(' · ')
                  : 'No company vehicle assigned'}
              </span>
              <span className="boss-employee-card-metrics">
                <span>
                  <small>This month</small>
                  <strong>
                    {formatNumber(item.monthDieselLitres, 1)} L diesel
                  </strong>
                </span>
                <span>
                  <small>Recorded cost</small>
                  <strong>
                    {item.monthCostRecordCount
                      ? formatEuro(item.monthCostEur)
                      : '—'}
                  </strong>
                </span>
              </span>
              <span className="boss-employee-card-foot">
                {item.latestActivityAt
                  ? `Last activity ${formatDateTime(item.latestActivityAt)}`
                  : 'No company fuel activity yet'}
                <span aria-hidden="true">
                  {selectedEmployee?.id === item.id ? 'Close details' : 'View records'}
                </span>
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p className="boss-table-empty boss-employee-empty">
          {loading
            ? 'Loading employees…'
            : searchText
              ? 'No employees match this search.'
              : 'No employees are registered yet.'}
        </p>
      )}

      {directory && directory.total > pageSize && (
        <div className="boss-pagination">
          <span>
            Showing {formatNumber((page - 1) * pageSize + 1)}–
            {formatNumber(Math.min(page * pageSize, directory.total))} of{' '}
            {formatNumber(directory.total)}
          </span>
          <div>
            <button
              type="button"
              disabled={page <= 1 || loading}
              onClick={() => setPage((current) => current - 1)}
            >
              Previous
            </button>
            <button
              type="button"
              disabled={page >= totalPages || loading}
              onClick={() => setPage((current) => current + 1)}
            >
              Next
            </button>
          </div>
        </div>
      )}

      {selectedEmployee && (
        <section
          className="boss-employee-detail"
          id="bossEmployeeDetail"
          aria-live="polite"
        >
          <div className="boss-detail-heading">
            <div>
              <p className="boss-overline">EMPLOYEE PROFILE</p>
              <h3>{selectedEmployee.name}</h3>
            </div>
            <button
              className="boss-small-icon-button"
              type="button"
              aria-label="Close employee details"
              onClick={() => setSelectedEmployee(null)}
            >
              <Icon name="close" size={16} />
            </button>
          </div>

          <div className="boss-employee-detail-summary">
            <span>
              <small>All-time company records</small>
              <strong>{formatNumber(selectedEmployee.recordCount)}</strong>
            </span>
            <span>
              <small>All-time diesel</small>
              <strong>{formatNumber(selectedEmployee.dieselLitres, 1)} L</strong>
            </span>
            <span>
              <small>This month</small>
              <strong>
                {formatNumber(selectedEmployee.monthRecordCount)} fills ·{' '}
                {formatNumber(selectedEmployee.monthDieselLitres, 1)} L
              </strong>
            </span>
            <span>
              <small>Recorded cost this month</small>
              <strong>
                {selectedEmployee.monthCostRecordCount
                  ? formatEuro(selectedEmployee.monthCostEur)
                  : '—'}
              </strong>
            </span>
          </div>

          <div className="boss-employee-assignment">
            <strong>Assigned company vehicles</strong>
            <span>
              {selectedEmployee.vehicleRegistrations.length
                ? selectedEmployee.vehicleRegistrations.map((registration) => (
                    <span className="boss-employee-vehicle-tag" key={registration}>
                      {registration}
                    </span>
                  ))
                : 'No company vehicle assigned'}
            </span>
          </div>

          <div className="boss-employee-history-heading">
            <div>
              <h4>Company fuel history</h4>
              <p>Choose a quick range or set exact dates.</p>
            </div>
            {records && (
              <span>
                {formatNumber(records.total)} record
                {records.total === 1 ? '' : 's'}
              </span>
            )}
          </div>

          <div className="boss-employee-date-filter">
            <div
              className="boss-employee-date-presets"
              role="group"
              aria-label="Quick date ranges"
            >
              {EMPLOYEE_DATE_PRESETS.map((preset) => (
                <button
                  key={preset.value}
                  type="button"
                  className={
                    recordRange.preset === preset.value ? 'selected' : ''
                  }
                  aria-pressed={recordRange.preset === preset.value}
                  onClick={() => selectDatePreset(preset.value)}
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <div className="boss-employee-date-inputs">
              <label>
                <span>From</span>
                <input
                  type="date"
                  value={recordRange.startDate}
                  onChange={(event) =>
                    updateRecordDate('startDate', event.target.value)
                  }
                  aria-label="Filter from date"
                />
              </label>
              <label>
                <span>To</span>
                <input
                  type="date"
                  value={recordRange.endDate}
                  onChange={(event) =>
                    updateRecordDate('endDate', event.target.value)
                  }
                  aria-label="Filter to date"
                />
              </label>
            </div>
          </div>

          {invalidDateRange ? (
            <p className="boss-employee-date-error" role="alert">
              The start date must be on or before the end date.
            </p>
          ) : (
            records && (
              <div className="boss-employee-range-summary">
                <span>
                  <small>Matching records</small>
                  <strong>{formatNumber(records.total)}</strong>
                </span>
                <span>
                  <small>Diesel in range</small>
                  <strong>{formatNumber(records.dieselLitres, 1)} L</strong>
                </span>
                <span>
                  <small>Recorded spend</small>
                  <strong>
                    {records.costRecordCount
                      ? formatEuro(records.costEur)
                      : '—'}
                  </strong>
                </span>
                <span>
                  <small>Records with cost</small>
                  <strong>
                    {formatNumber(records.costRecordCount)} of{' '}
                    {formatNumber(records.total)}
                  </strong>
                </span>
              </div>
            )
          )}

          {recordsError && (
            <div className="boss-inline-error" role="alert">
              Could not load fuel history: {recordsError}
            </div>
          )}
          {recordsLoading && !records ? (
            <div className="boss-loading" role="status">
              <span className="boss-spinner" />
              Loading fuel history…
            </div>
          ) : records?.items.length ? (
            <div className="boss-table-scroll">
              <table className="boss-fleet-table boss-employee-record-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Vehicle</th>
                    <th>Fuel</th>
                    <th>Volume</th>
                    <th>Cost</th>
                    <th>Mileage</th>
                    <th>Meter check</th>
                  </tr>
                </thead>
                <tbody>
                  {records.items.map((record) => (
                    <tr key={record.id}>
                      <td>{formatDateTime(record.createdAt)}</td>
                      <td>{record.registrationNumber}</td>
                      <td>{record.fuelType}</td>
                      <td>{formatNumber(record.litres, 1)} L</td>
                      <td>
                        {record.costEur > 0
                          ? formatEuro(record.costEur)
                          : 'Not recorded'}
                      </td>
                      <td>{formatMileage(record.mileageMiles)} mi</td>
                      <td>
                        <span
                          className={`boss-record-check status-${record.meterCheckStatus}`}
                        >
                          {record.meterCheckStatus.replaceAll('_', ' ')}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            !recordsLoading &&
            !recordsError && (
              <p className="boss-table-empty">
                No company fuel records found in this date range.
              </p>
            )
          )}

          {records && records.total > pageSize && (
            <div className="boss-pagination">
              <span>
                Showing{' '}
                {formatNumber((records.page - 1) * records.pageSize + 1)}–
                {formatNumber(
                  Math.min(records.page * records.pageSize, records.total)
                )}{' '}
                of {formatNumber(records.total)}
              </span>
              <div>
                <button
                  type="button"
                  disabled={recordsPage <= 1 || recordsLoading}
                  onClick={() => setRecordsPage((current) => current - 1)}
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={recordsPage >= recordTotalPages || recordsLoading}
                  onClick={() => setRecordsPage((current) => current + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </section>
      )}
    </section>
  );
}

function VehicleUsageList({ title, vehicles }) {
  const maximum = Math.max(...vehicles.map((vehicle) => vehicle.litres), 1);
  return (
    <div className="boss-usage-list">
      <h3>{title}</h3>
      {vehicles.length ? (
        vehicles.map((vehicle) => (
          <div className="boss-usage-row" key={vehicle.vehicleId}>
            <div>
              <span>{vehicle.registrationNumber}</span>
              <small>{formatNumber(vehicle.transactionCount)} fills</small>
            </div>
            <div className="boss-usage-track">
              <span
                style={{
                  width: `${Math.max(
                    4,
                    (vehicle.litres / maximum) * 100
                  )}%`
                }}
              />
            </div>
            <strong>{formatNumber(vehicle.litres, 1)} L</strong>
          </div>
        ))
      ) : (
        <p className="boss-table-empty">
          No recorded diesel fills in this period.
        </p>
      )}
    </div>
  );
}

function TransactionList({ transactions }) {
  return (
    <div className="boss-transactions">
      {transactions.map((transaction) => (
        <div className="boss-transaction-row" key={transaction.id}>
          <span className="boss-transaction-mark">
            <Icon name="fuel" size={15} />
          </span>
          <div>
            <strong>
              {transaction.fuelType} · {formatNumber(transaction.litres, 1)} L
            </strong>
            <small>
              {formatDateTime(transaction.createdAt)} ·{' '}
              {transaction.employeeName ?? 'Employee not recorded'}
            </small>
          </div>
          <span className="boss-transaction-cost">
            {transaction.costEur > 0
              ? formatEuro(transaction.costEur)
              : 'Cost not recorded'}
          </span>
        </div>
      ))}
    </div>
  );
}

function SortMark({ field, active, order }) {
  return (
    <span
      className={`boss-sort-mark${field === active ? ' active' : ''}`}
      aria-hidden="true"
    >
      {field === active ? (order === 'asc' ? '↑' : '↓') : '↕'}
    </span>
  );
}
