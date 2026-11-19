import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import companyLogo from '../../brusna-curious-cat-logo.png';
import BossDashboard from './BossDashboard.jsx';
import {
  apiUrl,
  clearAdminOperationalData,
  createEmployee,
  createVehicle,
  createFuelRecord,
  createGlobalMeterEvent,
  decideAdminMeterReadingReview,
  getAdminMeterReadingReviews,
  getAdminEmployeeFuelRecords,
  getAdminEmployees,
  getAdminFuelSummary,
  getAdminVehicles,
  getAssignedVehicle,
  getCurrentEmployee,
  getFuelRecords,
  getGlobalMeterHistory,
  getGlobalMeterSummary,
  getNctAlerts,
  getVehicleFuelRecords,
  getVehicleNctList,
  getVehicleRegistrationSuggestions,
  identifyVehicle,
  login,
  logout,
  previewFuelReading,
  provisionVehicleQr,
  recognizeMeterPhoto,
  startMeterPhotoSession,
  uploadMeterPhoto,
  updateEmployeeRole,
  updateEmployeeStatus,
  updateVehicleNct,
  verifyMeterPhoto
} from './api/client.js';
import {
  formatMileage
} from './utils/distance.js';
import {
  getCumulativeTotalDraftValue,
  formatRawMeterDigitsAsLitres,
  rawMeterDigitsToLitres
} from './utils/meterReadings.js';

const REPORT_EMAIL = 'fleet@yourcompany.com';
const SUBMISSION_NOTICE =
  'Fuel dispensed is calculated from the difference between accepted cumulative TOTAL readings. The original photo and OCR evidence are retained with the confirmed reading.';
const MAX_METER_PHOTO_BYTES = 10 * 1024 * 1024;

function meterPhotoFileType(file) {
  const fileType = file.type?.toLowerCase();
  if (fileType?.startsWith('image/')) return fileType;
  const extension = file.name.match(/\.([a-z0-9]{1,16})$/i)?.[1]?.toLowerCase();
  if (!extension) return '';
  return `image/${extension === 'jpg' ? 'jpeg' : extension}`;
}

function meterPhotoFileError(file) {
  const fileType = meterPhotoFileType(file);
  const declaredType = file.type?.toLowerCase();
  const mayBeCameraRaw =
    declaredType === 'application/octet-stream' ||
    declaredType?.startsWith('application/x-');
  if (
    (declaredType &&
      !declaredType.startsWith('image/') &&
      !mayBeCameraRaw) ||
    !fileType.startsWith('image/')
  ) {
    return 'Choose a file in a supported photo format.';
  }
  if (file.size === 0 || file.size > MAX_METER_PHOTO_BYTES) {
    return 'The photo must be larger than 0 bytes and no larger than 10 MB.';
  }
  return '';
}

async function createOptimizedOcrPhoto(file) {
  let decodedImage;
  try {
    if (typeof createImageBitmap === 'function') {
      decodedImage = await createImageBitmap(file);
    } else {
      throw new Error('ImageBitmap is unavailable.');
    }
  } catch {
    const url = URL.createObjectURL(file);
    try {
      decodedImage = await new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error('The selected photo could not be decoded.'));
        image.src = url;
      });
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  const scale = Math.min(
    1,
    3000 / Math.max(decodedImage.width, decodedImage.height)
  );
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(decodedImage.width * scale));
  canvas.height = Math.max(1, Math.round(decodedImage.height * scale));
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Could not prepare the iPhone photo for OCR.');
  context.drawImage(decodedImage, 0, 0, canvas.width, canvas.height);
  if (typeof decodedImage.close === 'function') decodedImage.close();

  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob(
      (result) =>
        result
          ? resolve(result)
          : reject(new Error('Could not create an optimized OCR photo.')),
      'image/jpeg',
      0.96
    );
  });
  return new File(
    [blob],
    `${file.name.replace(/\.[^.]+$/, '')}-ocr.jpg`,
    { type: 'image/jpeg' }
  );
}

function Brand() {
  return (
    <div className="sidebar-brand">
      <img
        className="sidebar-company-logo"
        src={companyLogo}
        alt="Brusna, the retrofit specialists"
      />
    </div>
  );
}

function AppIcon({ name, size = 18 }) {
  const shapes = {
    overview: (
      <>
        <rect x="3" y="3" width="8" height="8" rx="1.5" />
        <rect x="13" y="3" width="8" height="5" rx="1.5" />
        <rect x="13" y="10" width="8" height="11" rx="1.5" />
        <rect x="3" y="13" width="8" height="8" rx="1.5" />
      </>
    ),
    team: (
      <>
        <circle cx="9" cy="8" r="3" />
        <path d="M3.5 20v-1.4A5.5 5.5 0 0 1 9 13h.2a5.5 5.5 0 0 1 5.3 4.3" />
        <path d="M16 13.2a4.2 4.2 0 0 1 4.5 4.2V20h-5.8" />
        <path d="M16.5 4.9a3 3 0 0 1 0 5.9" />
      </>
    ),
    fuel: (
      <>
        <path d="M12 3s-6 7.2-6 11a6 6 0 0 0 12 0C18 10.2 12 3 12 3Z" />
        <path d="M9.5 15.5a2.5 2.5 0 0 0 2.5 2.5" />
      </>
    ),
    odometer: (
      <>
        <path d="M4.6 18a9 9 0 1 1 14.8 0" />
        <path d="m12 13 4-4" />
        <path d="M12 17v.01" />
        <path d="M3 20h18" />
      </>
    ),
    meter: (
      <>
        <path d="M5 18a8 8 0 1 1 14 0" />
        <path d="M12 14l3-4" />
        <path d="M5 18h14" />
      </>
    ),
    camera: (
      <>
        <path d="M4 7h3l1.5-2h7L17 7h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1Z" />
        <circle cx="12" cy="13" r="3" />
      </>
    ),
    upload: (
      <>
        <path d="M12 15V4m0 0L8 8m4-4 4 4" />
        <path d="M5 13v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5" />
      </>
    ),
    review: (
      <>
        <path d="M12 3 2.8 19a1.4 1.4 0 0 0 1.2 2h16a1.4 1.4 0 0 0 1.2-2L12 3Z" />
        <path d="M12 9v4m0 3v.01" />
      </>
    ),
    history: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    vehicle: (
      <>
        <path d="m5 11 1.5-4.5A2 2 0 0 1 8.4 5h7.2a2 2 0 0 1 1.9 1.5L19 11" />
        <path d="M3 11h18v7H3z" />
        <path d="M6 18v2m12-2v2M6 14h.01M18 14h.01" />
      </>
    ),
    registry: (
      <>
        <rect x="5" y="4" width="14" height="17" rx="2" />
        <path d="M9 4V3h6v1M8 9h8m-8 4h8m-8 4h3" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />
  };

  return (
    <svg
      className="app-icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {shapes[name]}
    </svg>
  );
}

function LoginArt({ onSuccessAnimationEnd }) {
  return (
    <div className="login-art" aria-hidden="true">
      <div className="art-grid" />
      <div className="art-copy">
        TRACK
        <br />
        <strong>
          THE
          <br />
          ESSENTIALS
        </strong>
      </div>
      <div className="art-road">
        <svg
          className="art-car-illustration"
          viewBox="0 0 420 160"
          aria-hidden="true"
          onAnimationEnd={(event) => {
            if (event.animationName === 'login-car-drive-away') {
              onSuccessAnimationEnd();
            }
          }}
        >
          <defs>
            <linearGradient id="login-car-paint" x1="0" x2="1" y1="0" y2="1">
              <stop offset="0" stopColor="#8bd7bd" stopOpacity=".3" />
              <stop offset=".58" stopColor="#22b98c" stopOpacity=".12" />
              <stop offset="1" stopColor="#10271f" stopOpacity=".48" />
            </linearGradient>
            <linearGradient id="login-car-glass" x1="0" x2="1" y1="0" y2="1">
              <stop offset="0" stopColor="#d7fff1" stopOpacity=".32" />
              <stop offset="1" stopColor="#8bd7bd" stopOpacity=".08" />
            </linearGradient>
          </defs>
          <g className="art-motion-lines">
            <path d="M14 105h32m-22 12h25m-34 12h28" />
          </g>
          <ellipse className="art-car-shadow" cx="210" cy="151" rx="157" ry="6" />
          <path
            className="art-car-body"
            d="M54 102h35l21-39c6-11 16-18 29-18h94c17 0 31 9 39 23l19 34h35c11 0 20 9 20 20v8H54v-12c0-9 0-16 0-16Z"
          />
          <path
            className="art-car-glass"
            d="m115 98 15-33q4-9 15-9h35v42Zm76-42h38q22 0 35 17l17 25h-90Z"
          />
          <path className="art-car-glass-highlight" d="M139 62h20m-24 6-10 23m83-29h18m-12 6h10" />
          <path className="art-car-rearview-stem" d="M242 58v6" />
          <rect className="art-car-rearview-mirror" x="236" y="64" width="14" height="5" rx="2.5" />
          <path className="art-car-rearview-glint" d="M239 65.5h8" />
          <path className="art-car-detail" d="M180 56v46M90 102h236M155 103v25m104-25v25" />
          <rect className="art-car-door-handle" x="210" y="111" width="18" height="6" rx="3" />
          <path className="art-car-grille" d="M357 123v5m4-5v5" />
          <path className="art-car-mirror-arm" d="M274 95l5-8.5" />
          <g transform="translate(-15 0)">
            <g transform="rotate(60 289 86.5)">
              <path className="art-car-mirror" d="M282 80c5-3 11-1 14 3l-1 6c-5-1-10 1-13 4-4-3-4-9 0-13Z" />
              <path className="art-car-mirror-face" d="M284 82c-2 2-3 5-2 7" />
            </g>
          </g>
          <path className="art-car-tail-light" d="M58 104v12" />
          <path className="art-car-headlight" d="M328 106c5-2 10-1 14 2l1 5c-5-2-10-2-16 0Z" />
          <path className="art-car-headlight-beam" d="m330 108 9 2" />
          {[144, 298].map((wheelX) => (
            <g
              key={wheelX}
              className="art-car-wheel-assembly"
              transform={`translate(${wheelX} 128)`}
            >
              <circle className="art-car-wheel" r="22" />
              <circle className="art-car-wheel-sidewall" r="18" />
              <g className="art-car-wheel-spin">
                <circle className="art-car-wheel-rim" r="14" />
                <path
                  className="art-car-wheel-spokes"
                  d="M0-12V-4 M10.4-6L3.5-2 M10.4 6L3.5 2 M0 12V4 M-10.4 6L-3.5 2 M-10.4-6L-3.5-2"
                />
                <circle className="art-car-hub" r="4" />
                <circle className="art-car-wheel-lug" cx="0" cy="-7.5" r="0.8" />
                <circle className="art-car-wheel-lug" cx="6.5" cy="-3.75" r="0.8" />
                <circle className="art-car-wheel-lug" cx="6.5" cy="3.75" r="0.8" />
                <circle className="art-car-wheel-lug" cx="0" cy="7.5" r="0.8" />
                <circle className="art-car-wheel-lug" cx="-6.5" cy="3.75" r="0.8" />
                <circle className="art-car-wheel-lug" cx="-6.5" cy="-3.75" r="0.8" />
              </g>
            </g>
          ))}
        </svg>
      </div>
      <div className="art-stats">
        <span>LIVE FLEET</span>
        <strong>24 / 7</strong>
      </div>
    </div>
  );
}

function ThemeToggle({ theme, onToggle }) {
  const isDark = theme === 'dark';

  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={onToggle}
      aria-label={`Switch to ${isDark ? 'light' : 'dark'} mode`}
      aria-pressed={isDark}
      title={`Switch to ${isDark ? 'light' : 'dark'} mode`}
    >
      {isDark ? (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M20.2 15.1A8.4 8.4 0 0 1 8.9 3.8 8.5 8.5 0 1 0 20.2 15.1Z" />
        </svg>
      )}
      <span>{isDark ? 'Light mode' : 'Dark mode'}</span>
    </button>
  );
}

function LoginScreen({
  error,
  loading,
  success,
  onLogin,
  onSuccessAnimationEnd,
  theme,
  onToggleTheme
}) {
  return (
    <div className={`login-screen${success ? ' auth-success' : ''}`}>
      <div className="login-panel">
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        <img
          className="login-company-logo"
          src={companyLogo}
          alt="Brusna, the retrofit specialists"
        />
        <h1>
          Every fill,
          <br />
          <em>accounted for.</em>
        </h1>
        <p className="login-copy">
          A clear, fast logbook for the vehicles that keep everything moving.
        </p>
        <form
          className={`login-form${success ? ' is-success' : ''}`}
          onSubmit={onLogin}
        >
          {success ? (
            <div className="login-success-message" role="status">
              <span className="login-success-icon">
                <AppIcon name="check" size={16} />
              </span>
              <span className="login-success-copy">
                <strong>You're signed in</strong>
                <small>Opening your workspace…</small>
              </span>
              <span className="login-success-spinner" aria-hidden="true" />
            </div>
          ) : (
            <>
              <label>
                Username or email
                <input
                  id="loginUsername"
                  name="username"
                  type="text"
                  autoComplete="username"
                  placeholder="Emma or you@example.com"
                  required
                  disabled={loading}
                />
              </label>
              <label>
                Password
                <input
                  id="loginPassword"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  disabled={loading}
                />
              </label>
              {error && <p className="auth-error" role="alert">{error}</p>}
              <button className="primary-button" type="submit" disabled={loading}>
                {loading ? 'Signing in...' : 'Sign in'} <span>-&gt;</span>
              </button>
            </>
          )}
        </form>
        {!success && <p className="demo-note">Use your employee account.</p>}
      </div>
      <LoginArt onSuccessAnimationEnd={onSuccessAnimationEnd} />
    </div>
  );
}

function SessionRestoreScreen() {
  return (
    <main className="session-restore" role="status" aria-busy="true">
      <img
        className="session-restore-logo"
        src={companyLogo}
        alt="Brusna, the retrofit specialists"
      />
      <div className="session-restore-status">
        <span className="session-restore-spinner" aria-hidden="true" />
        <span>Restoring your secure session...</span>
      </div>
    </main>
  );
}

function MeterPhotoFlow({ onVerified, vehicleId }) {
  const videoRef = useRef(null);
  const photoFileInputRef = useRef(null);
  const photoSessionTokenRef = useRef(null);
  const manualUploadSessionTokenRef = useRef(null);
  const photoUploadLockRef = useRef(false);
  const verificationLockRef = useRef(false);
  const [entryMode, setEntryMode] = useState('photo');
  const [photo, setPhoto] = useState(null);
  const [pendingPhoto, setPendingPhoto] = useState(null);
  const [pendingProcessingPhoto, setPendingProcessingPhoto] = useState(null);
  const [preparingPhoto, setPreparingPhoto] = useState(false);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [cameraStream, setCameraStream] = useState(null);
  const [openingCamera, setOpeningCamera] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStatus, setUploadStatus] = useState('');
  const [readingOcr, setReadingOcr] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState('');
  const [cumulativeTotalDraft, setCumulativeTotalDraft] = useState('');
  const [cumulativeTotalEdited, setCumulativeTotalEdited] = useState(false);
  const [manualCumulativeTotalDraft, setManualCumulativeTotalDraft] = useState('');
  const [manualEvidenceFile, setManualEvidenceFile] = useState(null);
  const [manualUploadedPhoto, setManualUploadedPhoto] = useState(null);
  const [manualConfirmed, setManualConfirmed] = useState(false);
  const [readingPreview, setReadingPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');

  useEffect(() => {
    if (!previewUrl) return undefined;
    return () => URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  useEffect(() => {
    if (!photo || photo.verifiedAt || cumulativeTotalEdited) return;
    setCumulativeTotalDraft(getCumulativeTotalDraftValue(photo));
  }, [photo, cumulativeTotalEdited]);

  useEffect(() => {
    setReadingPreview(null);
    setPreviewError('');
    if (
      !photo ||
      photo.verifiedAt ||
      !/^[0-9]{6}$/.test(cumulativeTotalDraft.trim())
    ) {
      setPreviewLoading(false);
      return undefined;
    }

    let active = true;
    const timeoutId = window.setTimeout(() => {
      setPreviewLoading(true);
      previewFuelReading({
        cumulativeTotalRawDigits: cumulativeTotalDraft.trim()
      }).then((preview) => {
        if (active) setReadingPreview(preview);
      }).catch((previewRequestError) => {
        if (active) setPreviewError(previewRequestError.message);
      }).finally(() => {
        if (active) setPreviewLoading(false);
      });
    }, 180);
    return () => {
      active = false;
      window.clearTimeout(timeoutId);
    };
  }, [cumulativeTotalDraft, photo]);

  useEffect(() => {
    const video = videoRef.current;
    if (!cameraStream || !video) return undefined;
    video.srcObject = cameraStream;
    video.play().catch((playError) => {
      setError(`Could not start the camera preview: ${playError.message}`);
    });
    return () => {
      video.srcObject = null;
      cameraStream.getTracks().forEach((track) => track.stop());
    };
  }, [cameraStream]);

  async function openCamera() {
    setError('');
    if (!navigator.mediaDevices?.getUserMedia) {
      setError(
        'Camera access is unavailable. Open this page in Safari over HTTPS and allow camera access.'
      );
      return;
    }

    setOpeningCamera(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1920 },
          height: { ideal: 1080 }
        }
      });
      setCameraStream(stream);
    } catch (cameraError) {
      if (cameraError.name === 'NotAllowedError') {
        setError('Camera access was denied. Allow camera access in Safari settings, then try again.');
      } else if (cameraError.name === 'NotFoundError') {
        setError('No camera was found on this device.');
      } else if (cameraError.name === 'NotReadableError') {
        setError('The camera is busy in another app. Close it there and try again.');
      } else {
        setError(`Could not open the camera: ${cameraError.message}`);
      }
    } finally {
      setOpeningCamera(false);
    }
  }

  async function capturePhoto() {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0 || video.videoHeight === 0) {
      setError('The camera is still starting. Wait a moment, then try again.');
      return;
    }

    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext('2d');
    if (!context) {
      setError('Could not prepare the camera image. Please try again.');
      return;
    }

    setCapturing(true);
    try {
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const imageBlob = await new Promise((resolve, reject) => {
        canvas.toBlob(
          (blob) =>
            blob
              ? resolve(blob)
              : reject(new Error('Could not capture the photo. Please try again.')),
          'image/jpeg',
          0.96
        );
      });
      const capturedPhoto = new File(
        [imageBlob],
        `meter-readings-${Date.now()}.jpg`,
        { type: 'image/jpeg' }
      );
      const fileError = meterPhotoFileError(capturedPhoto);
      if (fileError) throw new Error(fileError);
      photoSessionTokenRef.current = null;
      setPendingPhoto(capturedPhoto);
      setPendingProcessingPhoto(null);
      setPreviewUrl(URL.createObjectURL(capturedPhoto));
      setCameraStream(null);
      setCumulativeTotalEdited(false);
      setError('');
    } catch (captureError) {
      setError(captureError.message);
    } finally {
      setCapturing(false);
    }
  }

  async function handlePhotoFileSelected(event) {
    const selectedPhoto = event.currentTarget.files?.[0];
    event.currentTarget.value = '';
    if (!selectedPhoto) return;
    const fileError = meterPhotoFileError(selectedPhoto);
    if (fileError) {
      photoSessionTokenRef.current = null;
      setPendingPhoto(null);
      setPendingProcessingPhoto(null);
      setPreviewUrl(null);
      setError(fileError);
      return;
    }

    const fileType = meterPhotoFileType(selectedPhoto);
    const originalPhoto =
      selectedPhoto.type === fileType
        ? selectedPhoto
        : new File([selectedPhoto], selectedPhoto.name, {
            type: fileType,
            lastModified: selectedPhoto.lastModified
          });
    photoSessionTokenRef.current = null;
    setPhoto(null);
    setPendingPhoto(originalPhoto);
    setPendingProcessingPhoto(null);
    setPreviewUrl(URL.createObjectURL(originalPhoto));
    setCumulativeTotalDraft('');
    setCumulativeTotalEdited(false);
    setError('');
    if (fileType !== 'image/jpeg' && fileType !== 'image/png') {
      setPreparingPhoto(true);
      try {
        const processingPhoto = await createOptimizedOcrPhoto(originalPhoto);
        if (processingPhoto.size > 8 * 1024 * 1024) {
          throw new Error(
            'The optimized photo is too large for OCR. Choose a smaller photo.'
          );
        }
        setPendingProcessingPhoto(processingPhoto);
        setPreviewUrl(URL.createObjectURL(processingPhoto));
      } catch (processingError) {
        setError(processingError.message);
      } finally {
        setPreparingPhoto(false);
      }
    }
  }

  async function readUploadedPhoto(
    uploadedPhoto,
    processingPhoto = pendingProcessingPhoto
  ) {
    setReadingOcr(true);
    setUploadStatus('Reading meter...');
    setError('');
    try {
      setPhoto(
        await recognizeMeterPhoto(uploadedPhoto.id, processingPhoto)
      );
    } catch (requestError) {
      setPhoto({
        ...uploadedPhoto,
        ocrStatus: 'failed',
        ocrRequiresManualReview: true
      });
      setError(
        `Could not read the TOTAL row. Retry OCR or enter the six digits manually. ${requestError.message}`
      );
    } finally {
      setReadingOcr(false);
      setUploadStatus('');
    }
  }

  async function uploadCapturedPhoto() {
    if (!pendingPhoto || photoUploadLockRef.current) return;

    photoUploadLockRef.current = true;
    setUploading(true);
    setUploadProgress(0);
    setError('');
    try {
      const fileError = meterPhotoFileError(pendingPhoto);
      if (fileError) throw new Error(fileError);
      if (!photoSessionTokenRef.current) {
        setUploadStatus('Preparing photo upload...');
        const uploadSession = await startMeterPhotoSession(vehicleId);
        photoSessionTokenRef.current = uploadSession.sessionToken;
      }
      setUploadStatus('Uploading photo...');
      const uploadedPhoto = await uploadMeterPhoto(
        photoSessionTokenRef.current,
        pendingPhoto,
        'ocr',
        setUploadProgress
      );
      setPhoto(uploadedPhoto);
      setPendingPhoto(null);
      setCumulativeTotalEdited(false);
      photoSessionTokenRef.current = null;
      setUploading(false);
      await readUploadedPhoto(uploadedPhoto, pendingProcessingPhoto);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setUploading(false);
      photoUploadLockRef.current = false;
      setUploadStatus('');
    }
  }

  async function retryPhotoOcr() {
    if (!photo || readingOcr) return;
    await readUploadedPhoto(photo, pendingProcessingPhoto);
  }

  async function handleVerify(event) {
    event.preventDefault();
    if (!photo || verifying || verificationLockRef.current) return;
    verificationLockRef.current = true;
    setVerifying(true);
    setError('');
    try {
      const verifiedPhoto = await verifyMeterPhoto(photo.id, {
        confirmed: true,
        cumulativeTotalRawDigits: cumulativeTotalDraft.trim() || undefined
      });
      setPhoto(verifiedPhoto);
      onVerified(verifiedPhoto);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setVerifying(false);
      verificationLockRef.current = false;
    }
  }

  function enterManualMode() {
    setCameraStream(null);
    setPhoto(null);
    setPendingPhoto(null);
    setPendingProcessingPhoto(null);
    setPreviewUrl(null);
    setManualCumulativeTotalDraft('');
    setManualEvidenceFile(null);
    setManualUploadedPhoto(null);
    setPreviewUrl(null);
    photoSessionTokenRef.current = null;
    manualUploadSessionTokenRef.current = null;
    setManualConfirmed(false);
    setEntryMode('manual');
    setError('');
    onVerified(null);
  }

  function enterPhotoMode() {
    setEntryMode('photo');
    setManualUploadedPhoto(null);
    manualUploadSessionTokenRef.current = null;
    setManualConfirmed(false);
  }

  function handleManualEvidenceSelected(event) {
    const selectedPhoto = event.currentTarget.files?.[0];
    event.currentTarget.value = '';
    if (!selectedPhoto) return;
    const fileError = meterPhotoFileError(selectedPhoto);
    if (fileError) {
      manualUploadSessionTokenRef.current = null;
      setManualUploadedPhoto(null);
      setManualEvidenceFile(null);
      setPreviewUrl(null);
      setError(fileError);
      return;
    }

    const fileType = meterPhotoFileType(selectedPhoto);
    const originalPhoto =
      selectedPhoto.type === fileType
        ? selectedPhoto
        : new File([selectedPhoto], selectedPhoto.name, {
            type: fileType,
            lastModified: selectedPhoto.lastModified
          });
    manualUploadSessionTokenRef.current = null;
    setManualUploadedPhoto(null);
    setManualEvidenceFile(originalPhoto);
    setPreviewUrl(URL.createObjectURL(originalPhoto));
    setManualConfirmed(false);
    setError('');
  }

  async function handleManualConfirm(event) {
    event.preventDefault();
    if (!manualConfirmed || verifying || verificationLockRef.current) return;
    if (!manualEvidenceFile) {
      setError('A meter photo is required before confirming manual readings.');
      return;
    }
    const fileError = meterPhotoFileError(manualEvidenceFile);
    if (fileError) {
      setError(fileError);
      return;
    }
    const readings = {
      cumulativeTotalRawDigits: manualCumulativeTotalDraft.trim()
    };
    verificationLockRef.current = true;
    setVerifying(true);
    setUploadProgress(0);
    setError('');
    try {
      let uploadedPhoto = manualUploadedPhoto;
      if (!uploadedPhoto) {
        if (!manualUploadSessionTokenRef.current) {
          setUploadStatus('Preparing photo upload...');
          const uploadSession = await startMeterPhotoSession(vehicleId);
          manualUploadSessionTokenRef.current = uploadSession.sessionToken;
        }
        setUploadStatus('Uploading photo...');
        uploadedPhoto = await uploadMeterPhoto(
          manualUploadSessionTokenRef.current,
          manualEvidenceFile,
          'manual',
          setUploadProgress
        );
        setManualUploadedPhoto(uploadedPhoto);
        manualUploadSessionTokenRef.current = null;
      }
      setUploadStatus('Saving confirmed TOTAL...');
      const verifiedPhoto = await verifyMeterPhoto(uploadedPhoto.id, {
        confirmed: true,
        ...readings
      });
      setPhoto(verifiedPhoto);
      setManualUploadedPhoto(null);
      setEntryMode('photo');
      onVerified(verifiedPhoto);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setVerifying(false);
      verificationLockRef.current = false;
      setUploadStatus('');
    }
  }

  function startAnotherPhoto() {
    setCameraStream(null);
    setPhoto(null);
    setPendingPhoto(null);
    setPendingProcessingPhoto(null);
    setPreparingPhoto(false);
    setPreviewUrl(null);
    setCumulativeTotalDraft('');
    setCumulativeTotalEdited(false);
    photoSessionTokenRef.current = null;
    manualUploadSessionTokenRef.current = null;
    setError('');
    setEntryMode('photo');
    onVerified(null);
    void openCamera();
  }

  return (
    <section className="meter-photo-flow">
      <div className="meter-photo-heading">
        <span className="transaction-step" aria-hidden="true">01</span>
        <div className="meter-photo-heading-copy">
          <p className="eyebrow">METER VERIFICATION</p>
          <h4 className="meter-photo-title">
            <AppIcon name="meter" size={17} />
            <span>
              {entryMode === 'manual'
                ? 'Enter PIUSI TOTAL reading'
                : 'Capture PIUSI meter TOTAL'}
            </span>
          </h4>
          <p className="meter-photo-copy">
            {entryMode === 'manual'
              ? 'Only the smaller bottom row labelled TOTAL is used. Check every digit and its three implied decimal places.'
              : 'Keep the display centered and close. Only the smaller bottom row labelled TOTAL is used; keep its digits in focus and avoid glare.'}
          </p>
          <div
            className="reading-sheet-template"
            aria-label="PIUSI TOTAL scale"
          >
            <p><strong>TOTAL row:</strong> the last three digits are decimal places</p>
          </div>
        </div>
      </div>
      {entryMode === 'manual' && (
        <form className="meter-review-form" onSubmit={handleManualConfirm}>
          <p>
            Enter exactly six TOTAL digits. The decimal point is three places
            from the right: 261563 is 261.563 L, 261798 is 261.798 L, and
            267981 is 267.981 L. Manual entry still requires a supporting photo.
          </p>
          <label>
            Global Cumulative Total
            <input
              type="text"
              inputMode="numeric"
              autoComplete="off"
              pattern="[0-9]{6}"
              minLength={6}
              maxLength={6}
              required
              value={manualCumulativeTotalDraft}
              onChange={(event) => {
                setManualCumulativeTotalDraft(event.target.value);
                setManualConfirmed(false);
              }}
              placeholder="e.g. 261563 = 261.563 L"
            />
            {formatRawMeterDigitsAsLitres(manualCumulativeTotalDraft) != null && (
              <small aria-live="polite">
                Interpreted as {formatRawMeterDigitsAsLitres(manualCumulativeTotalDraft)} L
              </small>
            )}
          </label>
          <label>
            Supporting meter photo (required)
            <input
              type="file"
              accept="image/*"
              required
              onChange={handleManualEvidenceSelected}
            />
          </label>
          {manualEvidenceFile && previewUrl && (
            <img
              className="meter-photo-preview"
              src={previewUrl}
              alt="Selected original meter photo"
            />
          )}
          <label className="meter-confirmation">
            <input
              type="checkbox"
              required
              checked={manualConfirmed}
              onChange={(event) => {
                setManualConfirmed(event.target.checked);
              }}
            />
            I checked the complete TOTAL digits against the meter photo.
          </label>
          <button
            className="primary-button"
            type="submit"
            disabled={verifying || !manualEvidenceFile}
          >
            <AppIcon name="check" size={16} />
            {verifying
              ? uploadStatus || 'Saving confirmed TOTAL...'
              : 'Confirm manual TOTAL'}
          </button>
          {verifying && uploadStatus === 'Uploading photo...' && (
            <p role="status">{`Uploading photo (${uploadProgress}%)...`}</p>
          )}
          <button
            className="outline-button"
            type="button"
            onClick={enterPhotoMode}
          >
            Use photo and OCR instead
          </button>
          {manualConfirmed && (
            <p role="status">Manual TOTAL confirmed. Enter the odometer below.</p>
          )}
        </form>
      )}
      {entryMode === 'photo' && !photo && !pendingPhoto && !cameraStream && (
        <>
          <button
            className={`camera-start-button${openingCamera ? ' is-opening' : ''}`}
            type="button"
            onClick={() => void openCamera()}
            disabled={uploading || preparingPhoto || openingCamera}
            aria-busy={openingCamera}
            aria-label={openingCamera ? 'Opening camera' : 'Open camera'}
          >
            <span className="camera-start-icon">
              <AppIcon name="camera" size={20} />
            </span>
            <span className="camera-start-copy">
              <strong aria-live="polite">
                {openingCamera ? 'Opening camera...' : 'Open camera'}
              </strong>
              <small>Capture the bottom TOTAL row in one clear photo</small>
            </span>
            <span className="camera-start-arrow" aria-hidden="true">-&gt;</span>
          </button>
          <div className="meter-camera-actions">
            <button
              className="outline-button"
              type="button"
              onClick={() => photoFileInputRef.current?.click()}
            >
              Choose existing photo
            </button>
            <input
              ref={photoFileInputRef}
              className="meter-photo-file-input"
              type="file"
              accept="image/*"
              onChange={handlePhotoFileSelected}
            />
          </div>
        </>
      )}
      {entryMode === 'photo' && cameraStream && (
        <div className="meter-camera">
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            aria-label="Live meter camera preview"
          />
          <p className="meter-photo-copy">
            Keep the display centered and close so the bottom TOTAL row is
            readable. Hold the camera steady, focus on the digits, and avoid glare.
          </p>
          <div className="meter-camera-actions">
            <button
              className="primary-button"
              type="button"
              onClick={() => void capturePhoto()}
              disabled={capturing}
            >
              <AppIcon name="camera" size={16} />
              <span>{capturing ? 'Capturing...' : 'Take photo'}</span>
            </button>
            <button
              className="outline-button"
              type="button"
              onClick={() => setCameraStream(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {entryMode === 'photo' && pendingPhoto && !photo && (
        <div className="meter-capture-review">
          {previewUrl && (
            <img
              className="meter-photo-preview"
              src={previewUrl}
              alt="Captured PIUSI meter display preview"
            />
          )}
          <div className="meter-camera-actions">
            <button
              className="primary-button"
              type="button"
              onClick={() => void uploadCapturedPhoto()}
              disabled={uploading || preparingPhoto}
            >
              <AppIcon name="upload" size={16} />
              <span>
                {preparingPhoto
                  ? 'Preparing photo for OCR...'
                  : uploading
                    ? `Uploading photo (${uploadProgress}%)...`
                    : 'Upload photo'}
              </span>
            </button>
            <button
              className="outline-button"
              type="button"
              onClick={startAnotherPhoto}
              disabled={uploading || preparingPhoto}
            >
              <AppIcon name="camera" size={15} />
              Retake photo
            </button>
          </div>
          {(uploading || preparingPhoto) && (
            <p role="status">{preparingPhoto ? 'Preparing photo...' : uploadStatus}</p>
          )}
        </div>
      )}
      {error && (
        <p className="auth-error" role="alert">{error}</p>
      )}
      {entryMode === 'photo' && photo && (
        <div className="meter-review">
          {previewUrl && (
            <img
              className="meter-photo-preview"
              src={previewUrl}
              alt={`Uploaded PIUSI TOTAL meter reading for ${photo.registrationNumber}`}
            />
          )}
          <p role="status">
            Original photo saved securely for {photo.registrationNumber}.
          </p>
          <div className="meter-readings">
            <div>
              <span className="meter-reading-label">
                <AppIcon name="meter" size={14} />
                <span>
                  {photo.suggestedCumulativeTotalRawDigits
                    ? 'Suggested Global Cumulative Total'
                    : 'Unconfirmed TOTAL candidates'}
                </span>
              </span>
              <strong>{formatOcrCumulativeTotal(photo)}</strong>
              {!photo.suggestedCumulativeTotalRawDigits && (
                <>
                  <small className="meter-photo-copy">
                    Tesseract: {formatOcrCandidate(photo.ocrCumulativeTotalRawDigits)};
                    {' '}OpenCV: {formatOcrCandidate(photo.ocrCumulativeTotalSegmentRawDigits)}
                  </small>
                  {photo.ocrWarnings?.length > 0 && (
                    <ul className="meter-ocr-warnings" aria-label="OCR warnings">
                      {photo.ocrWarnings.map((warning, index) => (
                        <li key={`${warning}-${index}`}>{warning}</li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>
          </div>
          {(readingOcr || ['pending', 'processing'].includes(photo.ocrStatus)) && (
            <p role="status" aria-live="polite">Reading meter...</p>
          )}
          {photo.ocrRequiresManualReview && !readingOcr && (
            <p className="meter-ocr-warning" role="alert">
              Please check all six TOTAL digits against the original photo.
            </p>
          )}
          {['failed', 'unavailable'].includes(photo.ocrStatus) && !readingOcr && (
            <button
              className="outline-button"
              type="button"
              onClick={() => void retryPhotoOcr()}
            >
              Retry meter reading
            </button>
          )}
          {photo.verifiedAt ? (
            <div className="meter-readings verified-readings" role="status">
              <div>
                <span className="meter-reading-label">
                  <AppIcon name="meter" size={14} />
                  <span>Confirmed Global Cumulative Total</span>
                </span>
                <strong>
                  {photo.cumulativeTotalInteger == null
                    ? formatCumulativeTotal(photo.cumulativeTotalLitres)
                    : `${formatMilliLitres(photo.cumulativeTotalInteger)} L`}
                </strong>
                <small>
                  {photo.cumulativeTotalManuallyCorrected
                    ? 'Manually corrected from the original OCR suggestion.'
                    : 'Accepted unchanged from the OCR suggestion.'}
                </small>
              </div>
              <div>
                <span className="meter-reading-label">
                  <AppIcon name="fuel" size={14} />
                  <span>Fuel dispensed from TOTAL difference</span>
                </span>
                <strong>
                  {photo.currentFillMilliLitres == null
                    ? 'Cannot calculate'
                    : `${formatMilliLitres(photo.currentFillMilliLitres)} L`}
                </strong>
                <small>
                  Previous accepted global total:{' '}
                  {photo.previousGlobalTotalInteger == null
                    ? 'not established'
                    : `${formatMilliLitres(photo.previousGlobalTotalInteger)} L`}
                </small>
              </div>
              {photo.readingWarnings?.length > 0 && (
                <p className="meter-ocr-warning" role="alert">
                  This reading has validation notes. Contact an administrator if it needs review.
                </p>
              )}
              <button
                className="outline-button"
                type="button"
                onClick={startAnotherPhoto}
              >
                Capture another meter photo
              </button>
            </div>
          ) : (
            <form className="meter-review-form" onSubmit={handleVerify}>
              <p>
                Review the original photo and correct the six TOTAL digits if
                needed. Keep their order exactly as displayed; the decimal
                point is three places from the right.
              </p>
              <label>
                Global Cumulative Total
                <input
                  type="text"
                  inputMode="numeric"
                  autoComplete="off"
                  pattern="[0-9]{6}"
                  minLength={6}
                  maxLength={6}
                  required
                  disabled={readingOcr || verifying}
                  value={cumulativeTotalDraft}
                  onChange={(event) => {
                    setCumulativeTotalDraft(event.target.value);
                    setCumulativeTotalEdited(true);
                  }}
                  placeholder="e.g. 261563"
                />
                {formatRawMeterDigitsAsLitres(cumulativeTotalDraft) != null && (
                  <small aria-live="polite">
                    Interpreted as {formatRawMeterDigitsAsLitres(cumulativeTotalDraft)} L
                  </small>
                )}
              </label>
              {previewLoading && (
                <p role="status">Calculating against the previous accepted total...</p>
              )}
              {previewError && (
                <p className="auth-error" role="alert">{previewError}</p>
              )}
              {readingPreview && (
                <div className="notice" role="note">
                  <p>
                    Previous accepted total:{' '}
                    <strong>
                      {readingPreview.previousTotalMilliLitres == null
                        ? 'not established'
                        : `${formatMilliLitres(readingPreview.previousTotalMilliLitres)} L`}
                    </strong>
                  </p>
                  <p>
                    New cumulative total:{' '}
                    <strong>
                      {formatRawMeterDigitsAsLitres(cumulativeTotalDraft)} L
                    </strong>
                  </p>
                  <p>
                    Calculated fuel dispensed:{' '}
                    <strong>
                      {readingPreview.fillMilliLitres == null
                        ? 'not available'
                        : `${formatMilliLitres(readingPreview.fillMilliLitres)} L`}
                    </strong>
                  </p>
                  {readingPreview.warnings?.length > 0 && (
                    <ul className="meter-ocr-warnings" aria-label="Reading preview warnings">
                      {readingPreview.warnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              <label className="meter-confirmation">
                <input type="checkbox" required />
                I checked all TOTAL digits against the meter photo.
              </label>
              <button
                className="primary-button"
                type="submit"
                disabled={
                  verifying ||
                  previewLoading ||
                  !/^[0-9]{6}$/.test(cumulativeTotalDraft.trim())
                }
              >
                <AppIcon name="check" size={16} />
                {verifying ? 'Verifying...' : 'Confirm cumulative total'}
              </button>
              <button
                className="outline-button"
                type="button"
                onClick={startAnotherPhoto}
                disabled={verifying || readingOcr}
              >
                Retake photo
              </button>
            </form>
          )}
        </div>
      )}
    </section>
  );
}

function FuelForm({
  vehicle,
  onRecordCreated,
  allowVehicleSelection = false
}) {
  const [selectedVehicle, setSelectedVehicle] = useState(vehicle);
  const [registrationSearch, setRegistrationSearch] = useState(
    allowVehicleSelection ? '' : vehicle?.registrationNumber ?? ''
  );
  const [vehicleLookupLoading, setVehicleLookupLoading] = useState(false);
  const [vehicleLookupError, setVehicleLookupError] = useState('');
  const [vehicleSuggestions, setVehicleSuggestions] = useState([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [suggestionsError, setSuggestionsError] = useState('');
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(-1);
  const [meterPhoto, setMeterPhoto] = useState(null);
  const [calculatedFillConfirmed, setCalculatedFillConfirmed] = useState(false);
  const [odometer, setOdometer] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [flowKey, setFlowKey] = useState(0);
  const transactionFormRef = useRef(null);
  const submissionInProgressRef = useRef(false);
  const activeVehicle = allowVehicleSelection ? selectedVehicle : vehicle;
  const readingsVerified = Boolean(meterPhoto?.verifiedAt);
  const isManualEntry = Boolean(
    meterPhoto?.verifiedAt && meterPhoto.readingSource === 'manual'
  );
  const activeVehicleDetails = activeVehicle
    ? [activeVehicle.make, activeVehicle.model].filter(Boolean).join(' ')
    : '';
  const odometerBelowPrevious =
    activeVehicle?.lastRecordedOdometerMiles != null &&
    odometer !== '' &&
    Number(odometer) < activeVehicle.lastRecordedOdometerMiles;
  const calculatedFillNeedsConfirmation =
    meterPhoto?.fillCalculation === 'global_total_difference' &&
    !calculatedFillConfirmed;
  useEffect(() => {
    setSelectedVehicle(vehicle);
    setRegistrationSearch(
      allowVehicleSelection ? '' : vehicle?.registrationNumber ?? ''
    );
  }, [allowVehicleSelection, vehicle]);

  useEffect(() => {
    if (!allowVehicleSelection || !suggestionsOpen) return undefined;
    let active = true;
    const timeoutId = window.setTimeout(async () => {
      setSuggestionsLoading(true);
      setSuggestionsError('');
      try {
        const suggestions = await getVehicleRegistrationSuggestions(
          registrationSearch
        );
        if (active) {
          setVehicleSuggestions(suggestions);
          setActiveSuggestionIndex(registrationSearch.trim() ? 0 : -1);
        }
      } catch (error) {
        if (active) {
          setVehicleSuggestions([]);
          setSuggestionsError(error.message);
        }
      } finally {
        if (active) setSuggestionsLoading(false);
      }
    }, 180);
    return () => {
      active = false;
      window.clearTimeout(timeoutId);
    };
  }, [allowVehicleSelection, registrationSearch, suggestionsOpen]);

  async function selectVehicle(registrationNumber) {
    if (!registrationNumber.trim()) return;
    setVehicleLookupLoading(true);
    setVehicleLookupError('');
    try {
      const foundVehicle = await identifyVehicle(registrationNumber);
      setSelectedVehicle(foundVehicle);
      setRegistrationSearch(foundVehicle.registrationNumber);
      setSuggestionsOpen(false);
      setMeterPhoto(null);
      setOdometer('');
      setSubmitError('');
      setFlowKey((value) => value + 1);
    } catch (error) {
      setVehicleLookupError(error.message);
    } finally {
      setVehicleLookupLoading(false);
    }
  }

  async function handleVehicleLookup(event) {
    event.preventDefault();
    if (suggestionsLoading) return;
    if (activeSuggestionIndex >= 0 && vehicleSuggestions[activeSuggestionIndex]) {
      await selectVehicle(vehicleSuggestions[activeSuggestionIndex]);
      return;
    }
    if (registrationSearch.trim()) await selectVehicle(registrationSearch);
  }

  function handleVerifiedPhoto(photo) {
    setMeterPhoto(photo);
  }

  async function saveFuelRecord(odometerMiles) {
    if (
      !readingsVerified ||
      !activeVehicle ||
      submissionInProgressRef.current
    ) {
      return;
    }
    submissionInProgressRef.current = true;
    setSubmitting(true);
    setSubmitError('');
    try {
      const record = await createFuelRecord({
        meterPhotoId: meterPhoto.id,
        calculatedFillConfirmed,
        odometerMiles,
        ...(allowVehicleSelection
          ? { vehicleId: activeVehicle.id }
          : {})
      });
      transactionFormRef.current?.reset();
      setMeterPhoto(null);
      setCalculatedFillConfirmed(false);
      setOdometer('');
      setFlowKey((value) => value + 1);
      onRecordCreated(record);
    } catch (error) {
      setSubmitError(error.message);
    } finally {
      submissionInProgressRef.current = false;
      setSubmitting(false);
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await saveFuelRecord(Number(data.get('odometerMiles')));
  }

  return (
    <div className="fuel-form">
      {allowVehicleSelection && (
        <div className="boss-vehicle-picker">
          <form
            className="boss-vehicle-search"
            onSubmit={handleVehicleLookup}
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) {
                setSuggestionsOpen(false);
              }
            }}
          >
            <label htmlFor="bossVehicleRegistration">
              Find a vehicle by registration number
              <input
                id="bossVehicleRegistration"
                autoComplete="off"
                maxLength={32}
                value={registrationSearch}
                disabled={vehicleLookupLoading}
                role="combobox"
                aria-autocomplete="list"
                aria-expanded={suggestionsOpen}
                aria-controls="bossVehicleRegistrationSuggestions"
                aria-activedescendant={
                  activeSuggestionIndex >= 0
                    ? `bossVehicleSuggestion-${activeSuggestionIndex}`
                    : undefined
                }
                onFocus={() => setSuggestionsOpen(true)}
                onKeyDown={(event) => {
                  if (event.key === 'Escape') {
                    setSuggestionsOpen(false);
                  } else if (
                    event.key === 'ArrowDown' &&
                    vehicleSuggestions.length
                  ) {
                    event.preventDefault();
                    setActiveSuggestionIndex((index) =>
                      index >= vehicleSuggestions.length - 1 ? 0 : index + 1
                    );
                  } else if (
                    event.key === 'ArrowUp' &&
                    vehicleSuggestions.length
                  ) {
                    event.preventDefault();
                    setActiveSuggestionIndex((index) =>
                      index <= 0 ? vehicleSuggestions.length - 1 : index - 1
                    );
                  }
                }}
                onChange={(event) => {
                  const registration = event.target.value;
                  setRegistrationSearch(registration);
                  setVehicleSuggestions([]);
                  setActiveSuggestionIndex(-1);
                  setSuggestionsLoading(true);
                  setVehicleLookupError('');
                  setSuggestionsOpen(true);
                  if (
                    activeVehicle &&
                    registration.trim().toUpperCase() !==
                      activeVehicle.registrationNumber.toUpperCase()
                  ) {
                    setSelectedVehicle(null);
                    setMeterPhoto(null);
                    setOdometer('');
                    setSubmitError('');
                    setFlowKey((value) => value + 1);
                  }
                }}
                placeholder="e.g. 241-D-100"
              />
            </label>
            {suggestionsOpen && (
              <div
                className="boss-vehicle-suggestions"
                id="bossVehicleRegistrationSuggestions"
                role="listbox"
                aria-label="Vehicle registration suggestions"
              >
                {suggestionsLoading ? (
                  <p role="status">Loading registrations...</p>
                ) : suggestionsError ? (
                  <p className="auth-error" role="alert">{suggestionsError}</p>
                ) : vehicleSuggestions.length ? (
                  vehicleSuggestions.map((registrationNumber, index) => (
                    <button
                      key={registrationNumber}
                      id={`bossVehicleSuggestion-${index}`}
                      type="button"
                      role="option"
                      aria-selected={index === activeSuggestionIndex}
                      disabled={vehicleLookupLoading}
                      onMouseDown={(event) => event.preventDefault()}
                      onMouseEnter={() => setActiveSuggestionIndex(index)}
                      onClick={() => selectVehicle(registrationNumber)}
                    >
                      {registrationNumber}
                    </button>
                  ))
                ) : (
                  <p>
                    {registrationSearch.trim()
                      ? 'No matching registrations.'
                      : 'No active vehicle registrations found.'}
                  </p>
                )}
              </div>
            )}
          </form>
          <p className="boss-vehicle-search-hint">
            Type a few characters, then choose a suggested registration.
          </p>
          {vehicleLookupError && (
            <p className="auth-error" role="alert">{vehicleLookupError}</p>
          )}
          {activeVehicle && (
            <p className="boss-selected-vehicle" role="status">
              Selected vehicle: <strong>{activeVehicle.registrationNumber}</strong>
              {activeVehicleDetails && ` · ${activeVehicleDetails}`}
            </p>
          )}
        </div>
      )}
      {activeVehicle ? (
        <MeterPhotoFlow
          key={flowKey}
          vehicleId={allowVehicleSelection ? activeVehicle.id : null}
          onVerified={handleVerifiedPhoto}
        />
      ) : (
        <div className="notice" role="note">
          <span aria-hidden="true">i</span>
          <p>
            {allowVehicleSelection
              ? 'Find a registered vehicle above to record a fill.'
              : 'A vehicle must be assigned to your account before recording a fill.'}
          </p>
        </div>
      )}
      <form
        className="transaction-form"
        onSubmit={handleSubmit}
        ref={transactionFormRef}
      >
        <fieldset
          className={`transaction-entry${readingsVerified ? ' transaction-entry--ready' : ''}`}
          disabled={!activeVehicle || !readingsVerified || submitting}
        >
          <legend className="fieldset-heading">
            <span className="transaction-heading">
              <span className="transaction-step" aria-hidden="true">02</span>
              <span className="transaction-heading-copy">
                <strong className="transaction-title">
                  <AppIcon name="odometer" size={16} />
                  Transaction details
                </strong>
                <small>Complete your fuel record</small>
              </span>
            </span>
            <span
              className={`field-status${readingsVerified ? ' field-status--ready' : ''}`}
              role="status"
            >
              <span className="field-status-dot" aria-hidden="true" />
              {readingsVerified ? 'Ready' : 'Waiting for readings'}
            </span>
          </legend>
          <p className="transaction-help">
            {readingsVerified
              ? 'Enter the odometer shown on the vehicle dashboard.'
              : 'Confirm the cumulative TOTAL above to unlock odometer entry.'}
          </p>
          <label className="odometer-field" htmlFor="currentOdometer">
            <span className="odometer-label">
              <span>
                <AppIcon name="odometer" size={16} />
                Current mileage
              </span>
            </span>
            <span className="odometer-input-wrap">
              <input
                id="currentOdometer"
                name="odometerMiles"
                type="number"
                min="0"
                step="0.1"
                placeholder="e.g. 79850.0"
                value={odometer}
                onChange={(event) => {
                  setOdometer(event.target.value);
                }}
                onBlur={(event) => {
                  const isValid = event.currentTarget.checkValidity();
                  if (isValid && isManualEntry) {
                    setSubmitError('');
                  } else if (event.currentTarget.value && !isValid) {
                    event.currentTarget.reportValidity();
                  }
                }}
                aria-invalid={Boolean(odometerBelowPrevious)}
                aria-describedby={
                  activeVehicle?.lastRecordedOdometerMiles != null
                    ? 'odometer-help odometer-baseline'
                    : 'odometer-help'
                }
                required
              />
              <span aria-hidden="true">mi</span>
            </span>
            <span className="odometer-meta">
              <span id="odometer-help">Use the reading from the vehicle&apos;s dashboard.</span>
              {activeVehicle?.lastRecordedOdometerMiles != null && (
                <span className="odometer-baseline" id="odometer-baseline">
                  Last recorded mileage
                  <strong>
                    {formatMileage(activeVehicle.lastRecordedOdometerMiles)} mi
                  </strong>
                </span>
              )}
            </span>
          </label>
        </fieldset>
        {odometerBelowPrevious && (
          <p className="odometer-warning" role="alert">
            This is below the previous recorded mileage of{' '}
            {formatMileage(activeVehicle.lastRecordedOdometerMiles)} mi. An administrator
            must authorize this corrected value before it can be saved.
          </p>
        )}
        {readingsVerified && (
          <div className="meter-readings submission-readings">
            <div>
              <span className="meter-reading-label">
                <AppIcon name="fuel" size={14} />
                <span>Fuel dispensed</span>
              </span>
              <strong>
                {meterPhoto.currentFillMilliLitres == null
                  ? 'Not calculable'
                  : `${formatMilliLitres(meterPhoto.currentFillMilliLitres)} L`}
              </strong>
            </div>
            <div>
              <span className="meter-reading-label">
                <AppIcon name="meter" size={14} />
                <span>Previous accepted cumulative total</span>
              </span>
              <strong>
                {meterPhoto.previousGlobalTotalInteger == null
                  ? 'Not established'
                  : `${formatMilliLitres(meterPhoto.previousGlobalTotalInteger)} L`}
              </strong>
            </div>
          </div>
        )}
        {meterPhoto?.fillCalculation === 'global_total_difference' && (
          <div className="notice" role="note">
            <p>
              Fuel dispensed:{' '}
              <strong>
                {formatMilliLitres(meterPhoto.currentFillMilliLitres)} L
              </strong>
              {' '}from previous TOTAL {formatMilliLitres(meterPhoto.previousGlobalTotalInteger)} L to{' '}
              {formatMilliLitres(meterPhoto.cumulativeTotalInteger)} L.
            </p>
            <label className="meter-confirmation">
              <input
                type="checkbox"
                checked={calculatedFillConfirmed}
                onChange={(event) => {
                  setCalculatedFillConfirmed(event.target.checked);
                }}
              />
              I confirm the calculated fuel amount.
            </label>
          </div>
        )}
        {readingsVerified && meterPhoto?.previousGlobalTotalInteger == null && (
          <p className="odometer-warning" role="alert">
            No previous accepted cumulative total is established, so fuel cannot
            be calculated yet. Ask an authorized administrator to establish the
            meter baseline.
          </p>
        )}
        {submitError && <p className="auth-error" role="alert">{submitError}</p>}
        <div className="notice transaction-integrity-note" role="note">
          <span aria-hidden="true">✓</span>
          <p>{SUBMISSION_NOTICE}</p>
        </div>
        {isManualEntry && (
          <p className="manual-save-note">
            Your corrected TOTAL and supporting photo will be saved when you
            select Save fuel record.
          </p>
        )}
        <button
          className="primary-button submit-button"
          type="submit"
          disabled={
            !activeVehicle ||
            !readingsVerified ||
            !odometer.trim() ||
            !Number.isFinite(Number(odometer)) ||
            Number(odometer) < 0 ||
            meterPhoto?.previousGlobalTotalInteger == null ||
            calculatedFillNeedsConfirmation ||
            submitting
          }
        >
          <AppIcon name="fuel" size={17} />
          <span>{submitting ? 'Saving fuel record...' : 'Save fuel record'}</span>
        </button>
      </form>
    </div>
  );
}

function FuelMascotScene() {
  return (
    <svg className="fuel-scene" viewBox="0 0 520 290" aria-hidden="true">
      <defs>
        <linearGradient id="carPaint" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#35ad91" />
          <stop offset="1" stopColor="#087360" />
        </linearGradient>
        <linearGradient id="pumpPaint" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#315d50" />
          <stop offset="1" stopColor="#193b34" />
        </linearGradient>
      </defs>
      <rect className="scene-sky" width="520" height="290" rx="18" />
      <circle className="scene-sun" cx="73" cy="58" r="24" />
      <path className="scene-cloud" d="M112 69c1-10 15-15 24-8 7-16 31-12 33 4 14-4 22 13 12 22h-58c-12 0-17-10-11-18Z" />
      <path className="scene-ground" d="M0 192c89-25 147 1 232-5 96-7 169-20 288 1v102H0Z" />
      <path className="scene-road" d="M0 229c110-13 234 12 520-4v65H0Z" />
      <path className="scene-road-mark" d="M22 265h43m30-3h43m30-1h43m30-2h43" />

      <g className="scene-pump" transform="translate(-415 0)">
        <path d="M427 205V98c0-9 7-16 16-16h38c9 0 16 7 16 16v107Z" fill="url(#pumpPaint)" />
        <path d="M420 205h84v12h-84z" fill="#163a32" />
        <rect x="439" y="103" width="46" height="39" rx="7" fill="#d8f0df" />
        <circle cx="452" cy="119" r="4" fill="#ef9a59" />
        <circle cx="463" cy="114" r="4" fill="#ef9a59" />
        <circle cx="474" cy="119" r="4" fill="#ef9a59" />
        <ellipse cx="463" cy="128" rx="9" ry="6" fill="#ef9a59" />
        <circle cx="463" cy="94" r="4" fill="#c9ef69" />
      </g>

      <g className="fuel-car">
        <ellipse cx="231" cy="215" rx="164" ry="12" fill="#183c3426" />
        <path
          d="M66 192 78 168q5-13 25-16l41-5 27-31q11-14 31-14h68q22 0 38 19l27 30 37 8q17 4 21 20l5 14q2 8-8 10h-23c0-14-11-25-25-25s-25 11-25 25H168c0-14-11-25-25-25s-25 11-25 25H80q-13 0-14-11Z"
          fill="url(#carPaint)"
          stroke="#0c6759"
          strokeLinejoin="round"
          strokeWidth="2"
        />
        <path d="M157 169 180 131q6-10 19-10h19v48Z" fill="#c6eee2" />
        <path d="M227 112h46q18 0 30 16l27 41H227Z" fill="#a8d9cb" />
        <path d="M157 169 180 131q6-10 19-10h19m9-9h46q18 0 30 16l27 41" fill="none" stroke="#3b7568" strokeWidth="2" />
        <path d="M222 111v58" stroke="#286b5d" strokeWidth="5" />
        <path d="M149 169h187" fill="none" stroke="#568c7e" strokeWidth="2" />
        <path d="M258 169v23q0 3-4 7" fill="none" stroke="#0c6759" strokeOpacity=".65" strokeWidth="2" />
        <path className="cat-tail" d="M223 157c-13-3-17-12-11-18 6-6 14 0 10 6" />
        <path d="M270 168h15" stroke="#a8ead3" strokeLinecap="round" strokeWidth="3" />
        <path d="M87 183h305" stroke="#8be0bd" strokeOpacity=".7" strokeWidth="2" />
        <path d="M99 164h20" stroke="#f8d477" strokeLinecap="round" strokeWidth="7" />
        <path className="fuel-filler-door" d="M122 168q6-3 12 0v10q-6 3-12 0Z" />
        <circle className="fuel-filler-inlet" cx="127" cy="173" r="2" />
        <path d="M333 163l5-11" fill="none" stroke="#0c6759" strokeWidth="2" />
        <path className="cat-facing-mirror" d="M338 150q7-8 15-4l3 6q-8-2-15 3Z" />
        <path className="cat-facing-mirror-face" d="M340 150q6-5 10-3l-2 3q-4-1-6 2Z" />
        <path className="cat-facing-mirror-glint" d="m341 151 5-3" />
        <rect x="72" y="172" width="8" height="13" rx="3" fill="#ff987c" />
        <rect x="389" y="169" width="7" height="10" rx="3" fill="#fff0b0" />
        <path d="M391 183h5v9h-5" fill="none" stroke="#145f54" strokeLinecap="round" strokeWidth="3" />
        <text x="230" y="195" textAnchor="middle" fill="#eaf7e9" fontFamily="Manrope, sans-serif" fontSize="8" fontWeight="800" letterSpacing="1">BRUSNA</text>
        <circle cx="143" cy="201" r="25" fill="#172b28" stroke="#354d45" strokeWidth="3" />
        <circle cx="143" cy="201" r="13" fill="#91aa9c" />
        <circle cx="143" cy="201" r="5" fill="#506a5c" />
        <circle cx="341" cy="201" r="25" fill="#172b28" stroke="#354d45" strokeWidth="3" />
        <circle cx="341" cy="201" r="13" fill="#91aa9c" />
        <circle cx="341" cy="201" r="5" fill="#506a5c" />

        <g className="cat-driver" transform="translate(18 0)">
          <path d="M205 157c7-9 18-13 30-13 15 0 27 8 34 21v5h-64Z" fill="#e88a42" />
          <path d="M220 154c5-7 10-10 16-10s13 4 17 10l5 15h-43Z" fill="#f6e2d0" />
          <circle className="steering-wheel" cx="291" cy="159" r="11" />
          <path className="steering-spokes" d="M291 159v-7m0 7-7 6m7-6 7 6" />
          <circle cx="291" cy="159" r="2" fill="#31574b" />
          <path className="steering-column" d="m291 170-1-2" />
          <path className="cat-arm" d="M255 158c12-2 20 1 26 5m-35-3c10 1 20 4 34 5" />
          <g className="cat-head-motion">
            <g transform="translate(-28.4 -16.6) scale(1.12)">
              <path d="M208 133 204.5 112.6q-.8-5.3 4.1-2.4L228 124.4Zm44 0 3.5-20.4q.8-5.3-4.1-2.4L232 124.4Z" fill="#e88a42" stroke="#c96f35" strokeLinejoin="round" strokeWidth="1.5" />
              <path d="m210.5 127-1.8-13q-.3-1.6 1.2-.5l15.3 11.6c-5.1-1.1-9.9-.8-14.7 1.9Zm39 0 1.8-13q.3-1.6-1.2-.5l-15.3 11.6c5.1-1.1 9.9-.8 14.7 1.9Z" fill="#f3b2a1" />
              <path d="M211 116c3 2 6 4 9 7m29 0c-3-3-6-5-9-7" fill="none" stroke="#ffd0c0" strokeLinecap="round" strokeWidth="1.3" />
              <path d="M208 137c0-17 12-29 27-29s27 12 27 29c0 4-1 7-2 10l-5-3-1 6-5-2c-4 9-9 13-14 13s-10-4-14-13l-5 2-1-6-5 3c-1-3-2-6-2-10Z" fill="#e99047" stroke="#c96f35" strokeLinejoin="round" strokeWidth="1.5" />
              <path d="m220 115-4 7m8-9-3 7m30-5 3 7m-8-9 3 7" fill="none" stroke="#c96f35" strokeLinecap="round" strokeWidth="2.5" />
              <path d="M215 136c1-7 5-11 10-11s9 4 10 11c-1 7-5 11-10 11s-9-4-10-11Zm23 0c1-7 5-11 10-11s9 4 10 11c-1 7-5 11-10 11s-9-4-10-11Z" fill="#fff6ec" />
              <path d="M235 127c-2 5-2 11 0 16l2 4 2-4c2-5 2-11 0-16-1-2-3-2-4 0Z" fill="#fff6ec" />
              <path d="m212 143 6 3m39-3-6 3" fill="none" stroke="#c96f35" strokeLinecap="round" strokeWidth="2" />
              <path d="M212 145c2-7 9-9 15-6l10 5 10-5c6-3 13-1 15 6-1 10-8 17-17 17h-16c-9 0-16-7-17-17Z" fill="#fff6ec" />
              <path d="M215 149c3 2 6 2 9 1m26 0c3 1 6 1 9-1" fill="none" stroke="#efd6c0" strokeLinecap="round" strokeWidth="1.5" />
              <g className="cat-eyes">
                <ellipse cx="224" cy="137" rx="6.2" ry="7" fill="#fffaf4" stroke="#754c37" strokeWidth="0.8" />
                <ellipse cx="246" cy="137" rx="6.2" ry="7" fill="#fffaf4" stroke="#754c37" strokeWidth="0.8" />
                <ellipse cx="225" cy="138" rx="3.7" ry="4.8" fill="#6a9c74" />
                <ellipse cx="247" cy="138" rx="3.7" ry="4.8" fill="#6a9c74" />
                <ellipse cx="225" cy="139" rx="1.5" ry="3.4" fill="#292322" />
                <ellipse cx="247" cy="139" rx="1.5" ry="3.4" fill="#292322" />
                <circle cx="226" cy="135" r="1.5" fill="#fff" />
                <circle cx="248" cy="135" r="1.5" fill="#fff" />
              </g>
              <path d="M233 146c1-2 7-2 8 0l-4 5Z" fill="#fff" stroke="#d8898f" strokeLinejoin="round" strokeWidth="0.8" />
              <path d="M237 151c-2 4-6 4-8 1m8-1c2 4 6 4 8 1" fill="none" stroke="#6b4a43" strokeLinecap="round" strokeWidth="1.5" />
              <circle cx="220" cy="149" r="1" fill="#d7a982" />
              <circle cx="224" cy="151" r="1" fill="#d7a982" />
              <circle cx="254" cy="149" r="1" fill="#d7a982" />
              <circle cx="250" cy="151" r="1" fill="#d7a982" />
              <path d="m216 147-12-3m13 7-12 2m46-6 12-3m-13 7 12 2" fill="none" stroke="#f4ddc6" strokeLinecap="round" strokeWidth="1.5" />
            </g>
          </g>
          <path d="M222 160v5m28-5v5" stroke="#fff3e7" strokeLinecap="round" strokeWidth="6" />
          <g className="cat-paws">
            <circle className="cat-paw" cx="280" cy="160" r="4.5" />
            <circle className="cat-paw" cx="280" cy="166" r="4.5" />
          </g>
        </g>
      </g>

      <path className="pump-hose" d="M84 128C104 128 110 141 106 153 102 163 99 170 101 174 102 177 105 178 109 178" />
      <path className="pump-nozzle" d="M108 159h9l5 9v10h-14l-5-8v-5h5Z" />
      <path className="pump-nozzle-tip" d="M118 172h6" />
      <path className="cat-fuel-stream" d="M120 174h8" />
      <circle className="fuel-flow-drop fuel-flow-drop-one" cx="120" cy="174" r="1.8" />
      <circle className="fuel-flow-drop fuel-flow-drop-two" cx="124" cy="174" r="1.8" />
      <path className="scene-sparkle sparkle-one" d="m129 107 4 10 10 4-10 4-4 10-4-10-10-4 10-4Z" />
      <path className="scene-sparkle sparkle-two" d="m378 76 3 7 7 3-7 3-3 7-3-7-7-3 7-3Z" />
    </svg>
  );
}

function WorkflowGuide() {
  return (
    <aside className="workflow-guide" aria-labelledby="workflowGuideTitle">
      <p className="eyebrow">FLEET MASCOT</p>
      <h4 id="workflowGuideTitle">Brusna&apos;s pit stop</h4>
      <FuelMascotScene />
      <p className="mascot-story">
        Our orange co-pilot is ready to roll. Capture the PIUSI TOTAL row or
        enter its digits manually, then enter the odometer.
      </p>
      <div className="workflow-status" role="note">
        <span className="workflow-status-dot" aria-hidden="true" />
        <p>
          <strong>Check before saving.</strong> Fuel dispensed is calculated
          from consecutive accepted cumulative TOTAL readings.
        </p>
      </div>
    </aside>
  );
}

function formatDate(value) {
  return new Intl.DateTimeFormat('en-GB', {
    dateStyle: 'medium',
    timeStyle: 'short'
  }).format(new Date(value));
}

function formatLitres(value) {
  if (value == null) return 'Not recorded';
  return Number(value).toLocaleString('en-GB', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4
  });
}

function formatCurrentFill(value) {
  if (value == null) return 'Not recorded';
  const litres = Number(value);
  return Number.isInteger(litres)
    ? String(litres)
    : litres.toLocaleString('en-GB', { maximumFractionDigits: 3 });
}

function formatMilliLitres(value) {
  const milliLitres = Number(value);
  const sign = milliLitres < 0 ? '-' : '';
  const absoluteMilliLitres = Math.abs(milliLitres);
  const wholeLitres = Math.floor(absoluteMilliLitres / 1000);
  const fractionalDigits = String(absoluteMilliLitres % 1000).padStart(3, '0');
  return `${sign}${wholeLitres.toLocaleString('en-GB')}.${fractionalDigits}`;
}

function formatRawMeterReading(rawDigits) {
  const litres = formatRawMeterDigitsAsLitres(rawDigits);
  return litres == null ? `${rawDigits} raw digits` : `${litres} L (raw ${rawDigits})`;
}

function formatRecordFill(record) {
  return record.currentFillMilliLitres == null
    ? formatCurrentFill(record.currentFillLitres ?? record.litres)
    : formatMilliLitres(record.currentFillMilliLitres);
}

function formatCumulativeTotal(value) {
  if (value == null) return 'Not recorded';
  return Number(value).toLocaleString('en-GB', {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3
  });
}

function formatOcrCumulativeTotal(photo) {
  if (photo.suggestedCumulativeTotalRawDigits) {
    return `${formatRawMeterDigitsAsLitres(photo.suggestedCumulativeTotalRawDigits)} litres`;
  }
  const ocrDigits = photo.ocrCumulativeTotalRawDigits;
  const segmentDigits = photo.ocrCumulativeTotalSegmentRawDigits;
  if (
    typeof ocrDigits === 'string' &&
    /^[0-9]{6}$/.test(ocrDigits) &&
    ocrDigits === segmentDigits
  ) {
    return `${formatRawMeterDigitsAsLitres(ocrDigits)} litres`;
  }
  if (
    (typeof ocrDigits === 'string' && /^[0-9]{6}$/.test(ocrDigits)) ||
    (typeof segmentDigits === 'string' && /^[0-9]{6}$/.test(segmentDigits))
  ) {
    return 'Compare the unconfirmed candidates below';
  }
  return 'Check the TOTAL digits in the photo';
}

function formatOcrCandidate(rawDigits) {
  return typeof rawDigits === 'string' && /^[0-9]{6}$/.test(rawDigits)
    ? formatRawMeterReading(rawDigits)
    : 'No six-digit candidate';
}

function downloadJson(value, filename) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })
  );
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function recordWithMiles(record) {
  return {
    ...record,
    mileageUnit: 'mi'
  };
}

function downloadReport(record) {
  downloadJson(
    recordWithMiles(record),
    `fuel-report-${record.regNumber.replace(/\s+/g, '-')}-${record.id}.json`
  );
}

function emailReport(record) {
  const subject = `Fuel report: ${record.regNumber} / ${formatDate(record.createdAt)}`;
  const body = [
    'BRUSNA FUEL REPORT',
    `Registration: ${record.regNumber}`,
    `Driver: ${record.firstName} ${record.surname}`,
    `Fuel type: ${record.fuelType}`,
    `Mileage: ${formatMileage(record.mileageMiles)} mi`,
    `Tank capacity: ${record.capacity} litres`,
    `Current Fill: ${formatRecordFill(record)} litres`,
    `Cumulative Total: ${formatCumulativeTotal(record.cumulativeTotalLitres)} litres`,
    `Cumulative difference: ${formatLitres(record.meterDeltaLitres)} litres`,
    `Meter check: ${record.meterCheckStatus}`,
    `Cost: ${record.cost != null ? formatCost(record.cost) : 'Not supplied'}`,
    `Recorded: ${formatDate(record.createdAt)}`
  ].join('\n');
  window.location.href = `mailto:${REPORT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

function HistorySection({
  id = 'history',
  eyebrow = 'RECENT ACTIVITY',
  title = 'Filling actions',
  records,
  loading,
  onDownload,
  onEmail,
  onExport,
  showMeterPhoto = false
}) {
  return (
    <section id={id} className="history-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h3>{title}</h3>
        </div>
        <button
          className="outline-button"
          type="button"
          onClick={() => onExport(records)}
        >
          Export all <span>v</span>
        </button>
      </div>
      {loading ? (
        <div className="empty-state" role="status">
          <p>Loading saved records...</p>
        </div>
      ) : records.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">--</div>
          <h4>No fills recorded yet</h4>
          <p>Saved fuel reports will appear here.</p>
        </div>
      ) : (
        <div className="history-list">
          {records.map((record) => (
            <article className="history-item" key={record.id}>
              <div>
                <strong>{record.regNumber}</strong>
                <small>
                  {record.firstName} {record.surname} / {formatDate(record.createdAt)}
                </small>
                {record.isDemo && <small className="demo-record-tag">DEMO / TEST DATA</small>}
                <small>
                  Mileage: {formatMileage(record.mileageMiles)} mi
                </small>
                <small>
                  Current Fill: {formatRecordFill(record)} litres
                </small>
                <small>
                  Cumulative Total: {formatCumulativeTotal(record.cumulativeTotalLitres)} litres
                </small>
                {record.meterDeltaLitres !== null && (
                  <small>
                    Cumulative difference: {formatLitres(record.meterDeltaLitres)} litres
                  </small>
                )}
                {record.meterCheckStatus === 'discrepancy' && (
                  <small className="meter-discrepancy" role="alert">
                    Cumulative reading discrepancy - saved with warning
                  </small>
                )}
              </div>
              <div className="litres">
                {formatRecordFill(record)} L
              </div>
              <small className="record-cost">
                {record.cost != null ? `Cost: ${formatCost(record.cost)}` : 'Cost not supplied'}
              </small>
              <details className="transaction-details">
                <summary>Transaction details</summary>
                <dl>
                  <div>
                    <dt>Current Fill</dt>
                    <dd>{formatRecordFill(record)} litres</dd>
                  </div>
                  <div>
                    <dt>Cumulative Total</dt>
                    <dd>{formatCumulativeTotal(record.cumulativeTotalLitres)} litres</dd>
                  </div>
                  <div>
                    <dt>Meter comparison</dt>
                    <dd>
                      {record.meterCheckStatus}
                      {record.meterDeltaLitres !== null &&
                        ` (${formatLitres(record.meterDeltaLitres)} litres difference)`}
                    </dd>
                  </div>
                  <div>
                    <dt>Meter photo reference</dt>
                    <dd>
                      {record.meterPhotoId ?? 'No photo — readings entered manually'}
                    </dd>
                  </div>
                </dl>
              </details>
              {showMeterPhoto && record.meterPhotoId != null && (
                <a
                  className="admin-record-photo-link"
                  href={apiUrl(
                    `/api/management/global-meter/transactions/${record.id}/photo`
                  )}
                  target="_blank"
                  rel="noreferrer"
                >
                  View verified meter photo
                </a>
              )}
              <div className="history-actions">
                <button type="button" onClick={() => onDownload(record)}>
                  Download report .json
                </button>
                <button type="button" onClick={() => onEmail(record)}>
                  Email report
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function GlobalMeterDashboard({
  summary,
  history,
  loading,
  onRecordEvent,
  onOpenNct,
  showNctAlerts = true
}) {
  const [savingEvent, setSavingEvent] = useState(false);
  const [eventError, setEventError] = useState('');
  const [baselineDigits, setBaselineDigits] = useState('');
  const hasGlobalTotal =
    summary?.currentTotalInteger != null ||
    summary?.currentCumulativeTotalLitres != null;
  const baselinePreview = formatRawMeterDigitsAsLitres(baselineDigits);
  const latestPhotoUrl = summary?.lastMeterPhotoUrl;
  const recentHistory = history.slice(0, 3);

  async function handleEventSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const baselineCumulativeTotalLitres = rawMeterDigitsToLitres(
      String(data.get('baselineCumulativeTotalLitres') ?? '')
    );
    if (baselineCumulativeTotalLitres === null) {
      setEventError('Enter the meter digits using numbers only.');
      return;
    }

    setSavingEvent(true);
    setEventError('');
    try {
      await onRecordEvent({
        eventType: data.get('eventType'),
        baselineCumulativeTotalLitres,
        notes: data.get('notes')
      });
      form.reset();
      setBaselineDigits('');
    } catch (error) {
      setEventError(error.message);
    } finally {
      setSavingEvent(false);
    }
  }

  const eventForm = (
    <form
      className={`global-meter-event-form${hasGlobalTotal ? '' : ' is-initial-baseline'}`}
      onSubmit={handleEventSubmit}
    >
      <div className="global-meter-event-heading">
        <span className="global-meter-event-icon" aria-hidden="true">
          <AppIcon name="meter" size={19} />
        </span>
        <div className="global-meter-event-copy">
          <p className="eyebrow">AUTHORIZED CHANGE</p>
          <h4>
            {hasGlobalTotal
              ? 'Reset or replace the shared meter'
              : 'Establish the initial global meter baseline'}
          </h4>
          <p>
            {hasGlobalTotal
              ? 'Changes the fleet-wide baseline and records the reason in the audit history.'
              : 'Set the first verified reading for the shared meter. It will become the global cumulative total.'}
          </p>
        </div>
        <span className="global-meter-event-audit">
          <AppIcon name="check" size={13} />
          Audit trail
        </span>
      </div>
      <fieldset className="global-meter-event-types">
        <legend>Change type</legend>
        {hasGlobalTotal ? (
          <>
            <label className="global-meter-event-type-option">
              <input
                type="radio"
                name="eventType"
                value="reset"
                defaultChecked
                required
              />
              <span className="global-meter-event-type-icon" aria-hidden="true">
                <AppIcon name="meter" size={17} />
              </span>
              <span className="global-meter-event-type-copy">
                <strong>Meter reset</strong>
                <small>The existing counter has reset</small>
              </span>
              <span className="global-meter-event-type-check" aria-hidden="true">
                <AppIcon name="check" size={13} />
              </span>
            </label>
            <label className="global-meter-event-type-option">
              <input
                type="radio"
                name="eventType"
                value="replacement"
              />
              <span className="global-meter-event-type-icon" aria-hidden="true">
                <AppIcon name="vehicle" size={17} />
              </span>
              <span className="global-meter-event-type-copy">
                <strong>Meter replacement</strong>
                <small>A new shared meter has been installed</small>
              </span>
              <span className="global-meter-event-type-check" aria-hidden="true">
                <AppIcon name="check" size={13} />
              </span>
            </label>
          </>
        ) : (
          <label className="global-meter-event-type-option">
            <input
              type="radio"
              name="eventType"
              value="baseline"
              defaultChecked
              required
            />
            <span className="global-meter-event-type-icon" aria-hidden="true">
              <AppIcon name="meter" size={17} />
            </span>
            <span className="global-meter-event-type-copy">
              <strong>Initial baseline</strong>
              <small>This first reading becomes the shared total</small>
            </span>
            <span className="global-meter-event-type-check" aria-hidden="true">
              <AppIcon name="check" size={13} />
            </span>
          </label>
        )}
      </fieldset>
      <label className="global-meter-event-total-field">
        New cumulative total (meter digits)
        <input
          name="baselineCumulativeTotalLitres"
          type="text"
          inputMode="numeric"
          pattern="[0-9]{1,18}"
          maxLength={18}
          placeholder="e.g. 200000"
          value={baselineDigits}
          onChange={(event) => setBaselineDigits(event.target.value)}
          aria-describedby="globalMeterDigitsHelp"
          required
        />
        <small id="globalMeterDigitsHelp">
          Enter the displayed digits without a decimal point. 200000 = 200.000 L.
        </small>
        {baselineDigits && (
          <output className="global-meter-event-total-preview" aria-live="polite">
            {baselinePreview
              ? `Reading preview: ${baselinePreview} L`
              : 'Use digits only for this meter reading.'}
          </output>
        )}
      </label>
      <label className="global-meter-event-notes-field">
        Reason for change
        <input
          name="notes"
          minLength="5"
          maxLength="500"
          placeholder={
            hasGlobalTotal
              ? 'Explain why the meter is changing'
              : 'e.g. Initial reading at commissioning'
          }
          required
        />
      </label>
      {eventError && <p className="auth-error" role="alert">{eventError}</p>}
      <button
        className="primary-button"
        type="submit"
        disabled={savingEvent || loading || !summary}
      >
        {savingEvent
          ? 'Saving change...'
          : hasGlobalTotal
            ? 'Save meter change'
            : 'Set global meter baseline'}
      </button>
    </form>
  );

  return (
    <section className="global-meter-panel" id="globalMeter">
      <header className="global-meter-heading">
        <div>
          <p className="eyebrow">MANAGEMENT / SHARED PIUSI METER</p>
          <h3>Global cumulative total</h3>
          <p>One verified meter reading shared across the fleet.</p>
        </div>
        <span className="management-only-badge">ADMIN / BOSS ONLY</span>
      </header>

      <div className="global-meter-summary">
        <article className="global-meter-total-card">
          <span className="global-meter-label">GLOBAL CUMULATIVE TOTAL</span>
          <strong>
            {summary?.currentTotalInteger != null
            ? formatMilliLitres(summary.currentTotalInteger)
              : summary?.currentCumulativeTotalLitres == null
                ? '--'
                : formatCumulativeTotal(summary.currentCumulativeTotalLitres)}
            <span>L</span>
          </strong>
          <small>
            {!hasGlobalTotal
              ? loading
                ? 'Loading shared meter status'
                : 'Initial baseline required to start fleet tracking'
              : summary?.lastUpdateSource === 'fill'
              ? 'Latest accepted cumulative meter reading'
              : summary?.lastUpdateSource === 'baseline'
                ? 'Administrator-verified starting baseline'
                : summary?.lastUpdateSource === 'reset' ||
                  summary?.lastUpdateSource === 'replacement'
                ? `Authorized meter ${summary.lastUpdateSource}`
                : 'No meter reading has been accepted yet'}
          </small>
        </article>

        <dl className="global-meter-details">
          <div>
            <dt>Previous cumulative reading</dt>
            <dd>
              {summary?.previousTotalInteger != null
                ? `${formatMilliLitres(summary.previousTotalInteger)} L`
                : summary?.previousCumulativeTotalLitres == null
                  ? '--'
                  : `${formatCumulativeTotal(summary.previousCumulativeTotalLitres)} L`}
            </dd>
          </div>
          <div>
            <dt>Difference</dt>
            <dd>
              {summary?.differenceInteger != null
                ? `${formatMilliLitres(summary.differenceInteger)} L`
                : summary?.differenceLitres == null
                  ? '--'
                  : `${formatLitres(summary.differenceLitres)} L`}
            </dd>
          </div>
          <div>
            <dt>Last update</dt>
            <dd>{summary?.lastUpdatedAt ? formatDate(summary.lastUpdatedAt) : '--'}</dd>
          </div>
          <div>
            <dt>Submitted by</dt>
            <dd>{summary?.lastEmployeeName ?? '--'}</dd>
          </div>
          <div>
            <dt>Vehicle</dt>
            <dd>{summary?.lastVehicleRegistration ?? '--'}</dd>
          </div>
        </dl>

        <figure className="global-meter-photo">
          {latestPhotoUrl ? (
            <a href={apiUrl(latestPhotoUrl)} target="_blank" rel="noreferrer">
              <img
                src={apiUrl(latestPhotoUrl)}
                crossOrigin="use-credentials"
                alt="Meter photo for the latest accepted reading"
              />
            </a>
          ) : (
            <div className="global-meter-photo-empty">
              <AppIcon name="meter" size={24} />
              <span>No photo attached to this reading</span>
            </div>
          )}
          <figcaption>
            {summary?.lastMeterPhotoId
              ? `Verified meter photo #${summary.lastMeterPhotoId}`
              : 'Photo unavailable for this legacy reading'}
          </figcaption>
        </figure>
      </div>

      {!hasGlobalTotal && (
        <div className="global-meter-baseline-notice" role="status">
          <strong>Setup required</strong>
          <span>
            Record the first verified meter reading to start the shared fleet
            total. This establishes a starting point; it does not record a fuel fill.
          </span>
        </div>
      )}
      {!hasGlobalTotal && eventForm}

      {showNctAlerts && <NctAlertsCard onOpen={onOpenNct} />}

      <div className="global-meter-history">
        <div className="global-meter-history-heading">
          <div>
            <p className="eyebrow">AUDIT TRAIL</p>
            <h4>Meter reading history</h4>
          </div>
          <span
            className="global-meter-history-count"
            aria-label={`Latest ${recentHistory.length} of ${history.length} readings and events`}
          >
            <strong>{recentHistory.length}</strong>
            <span>latest</span>
            <span className="global-meter-history-count-separator" aria-hidden="true">/</span>
            <span>{history.length} total</span>
          </span>
        </div>
        {loading && recentHistory.length === 0 ? (
          <p className="global-meter-empty" role="status">Loading global meter history...</p>
        ) : recentHistory.length === 0 ? (
          <p className="global-meter-empty">No cumulative readings recorded yet.</p>
        ) : (
          <div className="global-meter-history-list">
            {recentHistory.map((entry) => (
              <details className="global-meter-history-item" key={entry.id}>
                <summary className="global-meter-history-summary">
                  <div className="global-meter-history-primary">
                    <span className={`global-meter-kind global-meter-kind-${entry.kind}`}>
                      {entry.kind === 'fill' ? 'FILL' : `METER ${entry.kind.toUpperCase()}`}
                    </span>
                    {entry.isDemo && (
                      <span className="global-meter-demo-tag">DEMO / TEST</span>
                    )}
                    <strong>
                      {entry.cumulativeTotalInteger != null
                        ? formatMilliLitres(entry.cumulativeTotalInteger)
                        : formatCumulativeTotal(entry.cumulativeTotalLitres)} L
                    </strong>
                    <time dateTime={entry.createdAt}>{formatDate(entry.createdAt)}</time>
                  </div>
                  <span className="global-meter-history-toggle">View details</span>
                </summary>
                <div className="global-meter-history-details">
                  <dl>
                    <div>
                      <dt>Employee</dt>
                      <dd>{entry.employeeName ?? '--'}</dd>
                    </div>
                    <div>
                      <dt>Vehicle</dt>
                      <dd>{entry.vehicleRegistration ?? '--'}</dd>
                    </div>
                    {entry.currentFillLitres != null && (
                      <div>
                        <dt>Calculated fill</dt>
                        <dd>
                          {entry.currentFillMilliLitres != null
                            ? `${(entry.currentFillMilliLitres / 1000).toFixed(3)} L`
                            : `${formatCurrentFill(entry.currentFillLitres)} L`}
                        </dd>
                      </div>
                    )}
                    {entry.topCurrentFillMilliLitres != null && (
                      <>
                        <div>
                          <dt>Top-row fill</dt>
                          <dd>
                            {(entry.topCurrentFillMilliLitres / 1000).toFixed(3)} L
                          </dd>
                        </div>
                        <div>
                          <dt>Top vs calculated</dt>
                          <dd>
                            {entry.currentFillMilliLitres == null
                              ? '--'
                              : `${((entry.topCurrentFillMilliLitres - entry.currentFillMilliLitres) / 1000).toFixed(3)} L`}
                          </dd>
                        </div>
                      </>
                    )}
                    <div>
                      <dt>Previous accepted total</dt>
                      <dd>
                        {entry.previousTotalInteger == null
                          ? '--'
                          : `${formatMilliLitres(entry.previousTotalInteger)} L`}
                      </dd>
                    </div>
                    <div>
                      <dt>Difference</dt>
                      <dd>
                        {entry.differenceInteger != null
                          ? `${formatMilliLitres(entry.differenceInteger)} L`
                          : entry.differenceLitres == null
                            ? '--'
                            : `${formatLitres(entry.differenceLitres)} L`}
                      </dd>
                    </div>
                    <div>
                      <dt>Status</dt>
                      <dd className={entry.status === 'discrepancy' ? 'meter-discrepancy' : ''}>
                        {entry.status}
                      </dd>
                    </div>
                    <div>
                      <dt>Reading source</dt>
                      <dd>{entry.readingSource || '--'}</dd>
                    </div>
                    <div>
                      <dt>Fill source</dt>
                      <dd>{entry.fillSource || '--'}</dd>
                    </div>
                    <div>
                      <dt>Verification</dt>
                      <dd>{entry.status}</dd>
                    </div>
                  </dl>
                  {entry.warnings?.length > 0 && (
                    <ul className="meter-ocr-warnings" aria-label="Meter warnings">
                      {entry.warnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  )}
                  {entry.notes && (
                    <p className="global-meter-history-note">
                      <strong>Notes</strong>
                      <span>{entry.notes}</span>
                    </p>
                  )}
                  {entry.meterPhotoUrl && (
                    <a
                      className="global-meter-history-photo"
                      href={entry.meterPhotoUrl}
                      target="_blank"
                      rel="noreferrer"
                    >
                      View meter photo
                    </a>
                  )}
                </div>
              </details>
            ))}
          </div>
        )}
      </div>

      {hasGlobalTotal && eventForm}
    </section>
  );
}

function DashboardSection({
  records,
  vehicle,
  loading,
  showFullHistory,
  showFlaggedReadings,
  showCumulativeTotal = true,
  showRecentActivity = true,
  showRecentExpanded = false,
  vehicleLabel = 'ASSIGNED VEHICLE'
}) {
  const latestRecord = records[0];
  const recentRecords = records.slice(0, 3);
  const latestCurrentFill =
    latestRecord?.currentFillLitres ?? latestRecord?.litres ?? null;
  const lastOdometerMiles = vehicle?.lastRecordedOdometerMiles;
  const recentReviewCount = recentRecords.filter(
    (record) => record.meterCheckStatus === 'discrepancy'
  ).length;
  const discrepancyCount = showFlaggedReadings
    ? records.filter((record) => record.meterCheckStatus === 'discrepancy').length
    : 0;

  return (
    <section
      id="overview"
      className={`overview-section${showRecentExpanded ? ' overview-section-user' : ''}${
        showRecentExpanded && recentReviewCount ? ' has-review-alert' : ''
      }`}
    >
      <header className="overview-header">
        <div>
          <p className="eyebrow">YOUR FUEL ACTIVITY</p>
          <h3>Overview</h3>
          <p className="overview-subtitle">
            A clear view of your latest readings and fill-ups.
          </p>
        </div>
        {showFullHistory && (
          <a className="overview-history-link" href="#history">
            View all fills <span aria-hidden="true">-&gt;</span>
          </a>
        )}
      </header>

      <div className={`overview-vehicle-card${vehicle ? '' : ' is-unassigned'}`}>
        <span className="overview-vehicle-icon" aria-hidden="true">
          <AppIcon name="vehicle" size={19} />
        </span>
        <div className="overview-vehicle-copy">
          <span className="overview-vehicle-label">
            {vehicleLabel}
          </span>
          {vehicle ? (
            <>
              <strong>{vehicle.registrationNumber}</strong>
              <small>
                {[
                  [vehicle.make, vehicle.model].filter(Boolean).join(' '),
                  vehicle.fuelType,
                  vehicle.tankCapacity != null
                    ? `${vehicle.tankCapacity} L tank`
                    : null
                ]
                  .filter(Boolean)
                  .join(' / ') || 'Vehicle ready for fuel logging'}
              </small>
              {vehicle.isDemo && (
                <span className="demo-record-tag">DEMO / TEST VEHICLE</span>
              )}
            </>
          ) : (
            <>
              <strong>No vehicle assigned</strong>
              <small>Ask an administrator to assign your vehicle before recording a fill.</small>
            </>
          )}
        </div>
        <span className="overview-vehicle-status">
          {vehicle ? 'READY' : 'SETUP NEEDED'}
        </span>
      </div>

      {recentReviewCount > 0 && (
        <div className="overview-review-alert" role="status">
          <span className="overview-review-alert-icon" aria-hidden="true">
            !
          </span>
          <span>
            <strong>
              {recentReviewCount} recent reading
              {recentReviewCount === 1 ? ' needs' : 's need'} review
            </strong>
            <small>
              Check the meter details before relying on these recorded values.
            </small>
          </span>
          <a href="#overviewRecent">Review activity</a>
        </div>
      )}

      <div
        className={`overview-metrics${showFlaggedReadings ? '' : ' overview-metrics-simple'}`}
      >
        <article className="overview-metric overview-metric-featured">
          <div className="overview-metric-heading">
            <span className="overview-metric-icon">
              <AppIcon name="fuel" />
            </span>
            <span className="overview-metric-label">LATEST FILL</span>
          </div>
          <strong className="overview-metric-value">
            {latestCurrentFill == null
              ? '--'
              : latestRecord?.currentFillMilliLitres == null
                ? formatCurrentFill(latestCurrentFill)
                : formatMilliLitres(latestRecord.currentFillMilliLitres)}
            {latestCurrentFill != null && (
              <span className="overview-metric-unit">L</span>
            )}
          </strong>
          <small>
            {latestRecord
              ? formatDate(latestRecord.createdAt)
              : 'No fills recorded yet'}
          </small>
        </article>
        <article className="overview-metric">
          <div className="overview-metric-heading">
            <span className="overview-metric-icon">
              <AppIcon name="odometer" />
            </span>
            <span className="overview-metric-label">LAST MILEAGE</span>
          </div>
          <strong className="overview-metric-value">
            {lastOdometerMiles != null
              ? formatMileage(lastOdometerMiles)
              : '--'}
            {lastOdometerMiles != null && (
              <span className="overview-metric-unit">mi</span>
            )}
          </strong>
          <small>
            {lastOdometerMiles != null
              ? 'From the latest vehicle entry'
              : 'No mileage recorded yet'}
          </small>
        </article>
        {showFlaggedReadings && (
          <article className="overview-metric overview-metric-warning">
            <div className="overview-metric-heading">
              <span className="overview-metric-icon">
                <AppIcon name="review" />
              </span>
              <span className="overview-metric-label">FLAGGED READINGS</span>
            </div>
            <strong className="overview-metric-value">{discrepancyCount}</strong>
            <small>
              {discrepancyCount === 1
                ? 'reading has a warning'
                : 'readings have warnings'}
            </small>
          </article>
        )}
      </div>

      {showRecentActivity && (
        <details
          className="overview-recent"
          id="overviewRecent"
          open={showRecentExpanded}
        >
          <summary className="overview-recent-heading">
            <div>
              <p className="eyebrow">RECENT ACTIVITY</p>
              <h4 id="overview-recent-title">Last 3 filling actions</h4>
            </div>
            <span className="overview-recent-count">
              {recentRecords.length} {recentRecords.length === 1 ? 'FILL' : 'FILLS'}
            </span>
            <span className="overview-recent-chevron" aria-hidden="true" />
          </summary>
          {loading ? (
            <p className="overview-empty" role="status">
              Loading your recent fills...
            </p>
          ) : recentRecords.length === 0 ? (
            <p className="overview-empty">
              Your filling actions will appear here after your first saved entry.
            </p>
          ) : (
            <ol className="overview-fill-list">
              {recentRecords.map((record) => {
                const status = record.meterCheckStatus;
                const statusLabel = {
                  matched: 'Matched',
                  baseline: 'Baseline',
                  legacy: 'Legacy',
                  discrepancy: 'Review needed'
                }[status] ?? 'Recorded';
                const statusClass =
                  status === 'discrepancy'
                    ? ' needs-review'
                    : status === 'matched'
                      ? ' matched'
                      : '';
                const statusIcon =
                  status === 'discrepancy'
                    ? 'review'
                    : status === 'matched'
                      ? 'check'
                      : 'history';
                return (
                  <li className="overview-fill-item" key={record.id}>
                    <span className="overview-fill-icon" aria-hidden="true">
                      <AppIcon name="fuel" size={16} />
                    </span>
                    <div className="overview-fill-main">
                      <strong>
                        {formatRecordFill(record)} L
                      </strong>
                      <time
                        className="overview-fill-date"
                        dateTime={record.createdAt}
                      >
                        <AppIcon name="history" size={13} />
                        {formatDate(record.createdAt)}
                      </time>
                    </div>
                    <div className="overview-fill-details">
                      {showCumulativeTotal && (
                        <span>
                          <AppIcon name="meter" size={13} />
                          <span>
                            Meter total:{' '}
                            {record.cumulativeTotalLitres != null
                              ? `${formatCumulativeTotal(record.cumulativeTotalLitres)} L`
                              : 'Not available'}
                          </span>
                        </span>
                      )}
                      <span>
                        <AppIcon name="odometer" size={13} />
                        <span>
                          {record.mileageMiles != null
                            ? `${formatMileage(record.mileageMiles)} mi`
                            : 'Odometer not recorded'}
                        </span>
                      </span>
                    </div>
                    <span className={`overview-fill-status${statusClass}`}>
                      <AppIcon name={statusIcon} size={13} />
                      <span>{statusLabel}</span>
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
        </details>
      )}
    </section>
  );
}

function RegistryDropdown({
  id,
  name,
  labelId,
  value,
  options,
  placeholder,
  disabled = false,
  required = false,
  error = '',
  onChange
}) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const dropdownRef = useRef(null);
  const optionRefs = useRef([]);
  const selectedOption = options.find((option) => option.value === value);
  const activeOption = options[activeIndex];
  const optionIndices = new Map(
    options.map((option, index) => [option.value, index])
  );
  const groupedOptions = options.reduce((groups, option) => {
    const label = option.group ?? '';
    const existing = groups.find((group) => group.label === label);
    if (existing) {
      existing.options.push(option);
    } else {
      groups.push({ label, options: [option] });
    }
    return groups;
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    function dismissDropdown(event) {
      if (!dropdownRef.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener('pointerdown', dismissDropdown);
    document.addEventListener('focusin', dismissDropdown);
    return () => {
      document.removeEventListener('pointerdown', dismissDropdown);
      document.removeEventListener('focusin', dismissDropdown);
    };
  }, [open]);

  useEffect(() => {
    if (open) {
      optionRefs.current[activeIndex]?.scrollIntoView({ block: 'nearest' });
    }
  }, [activeIndex, open]);

  function handleKeyDown(event) {
    if (disabled) return;
    const selectedIndex = options.findIndex((option) => option.value === value);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!options.length) return;
      if (!open) {
        setActiveIndex(
          selectedIndex >= 0
            ? selectedIndex
            : event.key === 'ArrowDown'
              ? 0
              : options.length - 1
        );
        setOpen(true);
      } else {
        const direction = event.key === 'ArrowDown' ? 1 : -1;
        setActiveIndex(
          (current) => (current + direction + options.length) % options.length
        );
      }
    } else if (open && (event.key === 'Home' || event.key === 'End')) {
      event.preventDefault();
      setActiveIndex(event.key === 'Home' ? 0 : options.length - 1);
    } else if (event.key === 'Escape' && open) {
      event.preventDefault();
      setOpen(false);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (open && activeOption) {
        onChange(activeOption.value);
        setOpen(false);
      } else {
        setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
        setOpen(true);
      }
    }
  }

  function toggleDropdown() {
    if (disabled) return;
    if (!open) {
      const selectedIndex = options.findIndex(
        (option) => option.value === value
      );
      setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
    }
    setOpen((current) => !current);
  }

  return (
    <>
      <input type="hidden" name={name} value={value} readOnly />
      <div
        className={`admin-registry-dropdown${open ? ' is-open' : ''}${error ? ' has-error' : ''}`}
        ref={dropdownRef}
      >
        <button
          id={`${id}Trigger`}
          className="admin-registry-dropdown-trigger"
          type="button"
          role="combobox"
          aria-labelledby={`${labelId} ${id}Value`}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={`${id}Options`}
          aria-activedescendant={
            open && activeOption ? `${id}Option${activeIndex}` : undefined
          }
          aria-required={required}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? `${id}Error` : undefined}
          disabled={disabled}
          onClick={toggleDropdown}
          onKeyDown={handleKeyDown}
        >
          <span className="admin-registry-dropdown-icon" aria-hidden="true">
            {selectedOption?.mark ? (
              selectedOption.mark
            ) : (
              <AppIcon name={selectedOption?.icon ?? 'vehicle'} size={17} />
            )}
          </span>
          <span className="admin-registry-dropdown-value">
            <strong id={`${id}Value`}>
              {selectedOption?.label ?? placeholder}
            </strong>
            <small>
              {selectedOption?.description ??
                (required ? 'Select an option to continue' : 'Choose a role')}
            </small>
          </span>
          {selectedOption?.meta && (
            <span className="admin-registry-dropdown-meta">
              {selectedOption.meta}
            </span>
          )}
          <span className="admin-registry-dropdown-chevron" aria-hidden="true" />
        </button>
        {open && (
          <div
            className="admin-registry-dropdown-menu"
            id={`${id}Options`}
            role="listbox"
            aria-labelledby={labelId}
          >
            {groupedOptions.map((group) => (
              <div
                className="admin-registry-dropdown-group"
                key={group.label || 'options'}
                role="group"
                aria-label={group.label || undefined}
              >
                {group.label && (
                  <p className="admin-registry-dropdown-group-label" aria-hidden="true">
                    {group.label}
                  </p>
                )}
                {group.options.map((option) => {
                  const index = optionIndices.get(option.value) ?? 0;
                  const isSelected = option.value === value;
                  const isActive = index === activeIndex;
                  return (
                    <div
                      className={`admin-registry-dropdown-option${isActive ? ' is-active' : ''}${isSelected ? ' is-selected' : ''}`}
                      id={`${id}Option${index}`}
                      key={option.value}
                      ref={(element) => {
                        optionRefs.current[index] = element;
                      }}
                      role="option"
                      aria-selected={isSelected}
                      onMouseEnter={() => setActiveIndex(index)}
                      onClick={() => {
                        onChange(option.value);
                        setOpen(false);
                      }}
                    >
                      <span className="admin-registry-dropdown-option-icon" aria-hidden="true">
                        {option.mark ? (
                          option.mark
                        ) : (
                          <AppIcon name={option.icon ?? 'vehicle'} size={16} />
                        )}
                      </span>
                      <span className="admin-registry-dropdown-option-copy">
                        <strong>{option.label}</strong>
                        <small>{option.description}</small>
                      </span>
                      {option.meta && (
                        <span className="admin-registry-dropdown-meta">
                          {option.meta}
                        </span>
                      )}
                      {isSelected && (
                        <span className="admin-registry-dropdown-check" aria-hidden="true">
                          <AppIcon name="check" size={14} />
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
            {!options.length && (
              <p className="admin-registry-dropdown-empty">No options available.</p>
            )}
          </div>
        )}
      </div>
      {error && (
        <span className="admin-registry-dropdown-error" id={`${id}Error`} role="alert">
          {error}
        </span>
      )}
    </>
  );
}

function AdminPanel({ onNotify }) {
  const [vehicles, setVehicles] = useState([]);
  const [vehiclesLoading, setVehiclesLoading] = useState(true);
  const [vehicleLoadError, setVehicleLoadError] = useState('');
  const [qrProvision, setQrProvision] = useState(null);
  const [employeeVehicleMode, setEmployeeVehicleMode] = useState('existing');
  const [employeeRole, setEmployeeRole] = useState('employee');
  const [selectedVehicleId, setSelectedVehicleId] = useState('');
  const [vehicleSelectionError, setVehicleSelectionError] = useState('');

  useEffect(() => {
    let active = true;
    getAdminVehicles()
      .then((registeredVehicles) => {
        if (!active) return;
        setVehicles(registeredVehicles);
        setVehicleLoadError('');
        setVehiclesLoading(false);
        if (!registeredVehicles.length) {
          setEmployeeVehicleMode((mode) =>
            mode === 'existing' ? 'none' : mode
          );
        }
      })
      .catch((error) => {
        if (!active) return;
        setVehicleLoadError(error.message);
        setVehiclesLoading(false);
        setEmployeeVehicleMode((mode) =>
          mode === 'existing' ? 'none' : mode
        );
        onNotify(`Could not load vehicle registry: ${error.message}`);
      });
    return () => {
      active = false;
    };
  }, [onNotify]);

  async function handleAddEmployee(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const vehicleMode = data.get('vehicleMode');
    const vehicleId =
      vehicleMode === 'existing' ? selectedVehicleId : '';
    if (vehicleMode === 'existing' && !vehicleId) {
      setVehicleSelectionError('Choose a registered vehicle to continue.');
      document.getElementById('registryVehicleTrigger')?.focus();
      return;
    }
    const selectedVehicle = vehicleId
      ? vehicles.find((vehicle) => vehicle.id === Number(vehicleId))
      : null;
    const registrationNumber =
      vehicleMode === 'new' ? data.get('vehicleRegistrationNumber') : '';
    try {
      const employee = await createEmployee({
        name: data.get('name'),
        email: data.get('email'),
        password: data.get('password'),
        role: employeeRole,
        vehicle_id: vehicleId ? Number(vehicleId) : null,
        vehicle_registration_number: registrationNumber || null,
        vehicle_make:
          vehicleMode === 'new'
            ? String(data.get('vehicleMake') ?? '').trim() || null
            : null,
        vehicle_model:
          vehicleMode === 'new'
            ? String(data.get('vehicleModel') ?? '').trim() || null
            : null,
        vehicle_fuel_type:
          vehicleMode === 'new' ? data.get('vehicleFuelType') || null : null,
        vehicle_is_company_vehicle:
          vehicleMode !== 'new' || data.get('vehicleIsCompany') === 'on',
        vehicle_tank_capacity:
          vehicleMode === 'new' && data.get('vehicleTankCapacity')
            ? Number(data.get('vehicleTankCapacity'))
            : null,
        nct_expiry_date:
          vehicleMode === 'new' ? data.get('nctExpiryDate') || null : null
      });
      form.reset();
      setEmployeeRole('employee');
      setSelectedVehicleId('');
      setVehicleSelectionError('');
      setEmployeeVehicleMode(
        vehicles.length > 0 || vehicleMode === 'new'
          ? 'existing'
          : 'none'
      );
      const assignedVehicle = employee.assignedVehicle ?? selectedVehicle;
      if (assignedVehicle) {
        setVehicles((current) => {
          const alreadyRegistered = current.some(
            (vehicle) => vehicle.id === assignedVehicle.id
          );
          const updated = alreadyRegistered
            ? current.map((vehicle) =>
                vehicle.id === assignedVehicle.id ? assignedVehicle : vehicle
              )
            : [...current, assignedVehicle];
          return updated.sort((first, second) =>
            first.registrationNumber.localeCompare(second.registrationNumber)
          );
        });
      }
      const role = employee.role === 'boss' ? 'Boss' : 'Employee';
      if (vehicleMode === 'new' && assignedVehicle) {
        try {
          const provision = await provisionVehicleQr(assignedVehicle.id);
          setQrProvision({ ...provision, id: assignedVehicle.id });
          onNotify(
            `${role} account created, ${assignedVehicle.registrationNumber} registered and assigned, and its QR code generated.`
          );
        } catch (error) {
          onNotify(
            `${role} and vehicle created, but QR generation failed: ${error.message}`
          );
        }
        return;
      }
      onNotify(
        assignedVehicle
          ? `${role} account created and ${assignedVehicle.registrationNumber} assigned.`
          : `${role} account created.`
      );
    } catch (error) {
      onNotify(`Could not create employee: ${error.message}`);
    }
  }

  async function handleAddVehicle(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    let vehicle;
    try {
      vehicle = await createVehicle({
        registration_number: data.get('registrationNumber'),
        make: String(data.get('make') ?? '').trim() || null,
        model: String(data.get('model') ?? '').trim() || null,
        fuel_type: data.get('fuelType') || null,
        is_company_vehicle: data.get('isCompanyVehicle') === 'on',
        tank_capacity: data.get('tankCapacity')
          ? Number(data.get('tankCapacity'))
          : null,
        nct_expiry_date: data.get('nctExpiryDate') || null
      });
      form.reset();
      setVehicles((current) =>
        [...current, vehicle].sort((first, second) =>
          first.registrationNumber.localeCompare(second.registrationNumber)
        )
      );
      const provision = await provisionVehicleQr(vehicle.id);
      setQrProvision({ ...provision, id: vehicle.id });
      onNotify('Vehicle added and its QR code generated.');
    } catch (error) {
      onNotify(
        vehicle
          ? `Vehicle added, but QR generation failed: ${error.message}`
          : `Could not add vehicle: ${error.message}`
      );
    }
  }

  const assignableVehicles = vehicles;
  const unassignedVehicles = assignableVehicles.filter(
    (vehicle) => (vehicle.employeeCount ?? 0) === 0
  );
  const assignedVehicles = assignableVehicles.filter(
    (vehicle) => (vehicle.employeeCount ?? 0) > 0
  );
  const roleOptions = [
    {
      value: 'employee',
      label: 'Employee',
      description: 'Standard access to assigned vehicles and fuel records.',
      mark: 'E',
      meta: 'STANDARD'
    },
    {
      value: 'boss',
      label: 'Boss',
      description: 'Management access to fleet summaries and NCT monitoring.',
      mark: 'B',
      meta: 'MANAGEMENT'
    }
  ];
  const makeVehicleOption = (vehicle, assigned) => {
    const details = [vehicle.make, vehicle.model].filter(Boolean).join(' ');
    const capacity =
      vehicle.tankCapacity == null ? '' : ` · ${vehicle.tankCapacity} L`;
    const employeeCount = vehicle.employeeCount ?? 0;
    return {
      value: String(vehicle.id),
      label: vehicle.registrationNumber,
      icon: 'vehicle',
      description: `${details || 'Make and model not listed'}${capacity}`,
      meta: assigned
        ? `${vehicle.isCompanyVehicle === false ? 'PERSONAL · ' : ''}${employeeCount} ${employeeCount === 1 ? 'EMPLOYEE' : 'EMPLOYEES'}`
        : `${vehicle.isCompanyVehicle === false ? 'PERSONAL · ' : ''}UNASSIGNED`,
      group: assigned
        ? `Assigned · available to share (${assignedVehicles.length})`
        : `Unassigned vehicles (${unassignedVehicles.length})`
    };
  };
  const vehicleOptions = [
    ...unassignedVehicles.map((vehicle) => makeVehicleOption(vehicle, false)),
    ...assignedVehicles.map((vehicle) => makeVehicleOption(vehicle, true))
  ];

  return (
    <section className="admin-panel admin-registry-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">ADMINISTRATION</p>
          <h3>Fleet registry</h3>
          <p>Manage staff access and registered vehicles.</p>
        </div>
        <span className="management-only-badge">ADMIN ONLY</span>
      </div>
      <div className="admin-forms">
        <form
          className="login-form admin-registry-form admin-registry-employee-form"
          onSubmit={handleAddEmployee}
          aria-labelledby="registryEmployeeTitle"
        >
          <h4 id="registryEmployeeTitle">Add employee</h4>
          <p className="admin-registry-help">
            Create an account and optionally link a vehicle. Fields marked * are
            required.
          </p>
          <label>
            <span className="admin-registry-label-line">
              Full name <span className="admin-registry-required">*</span>
            </span>
            <input name="name" autoComplete="name" required />
          </label>
          <label>
            <span className="admin-registry-label-line">
              Email address <span className="admin-registry-required">*</span>
            </span>
            <input name="email" type="email" autoComplete="off" required />
          </label>
          <div className="admin-registry-dropdown-field">
            <span className="admin-registry-label-line" id="registryRoleLabel">
              Account role <span className="admin-registry-required">*</span>
            </span>
            <RegistryDropdown
              id="registryRole"
              name="role"
              labelId="registryRoleLabel"
              value={employeeRole}
              options={roleOptions}
              placeholder="Choose an account role"
              required
              onChange={setEmployeeRole}
            />
          </div>
          <label>
            <span className="admin-registry-label-line">
              Temporary password <span className="admin-registry-required">*</span>
            </span>
            <input
              name="password"
              type="password"
              minLength="12"
              autoComplete="new-password"
              aria-describedby="registryPasswordHint"
              required
            />
            <span className="admin-registry-field-hint" id="registryPasswordHint">
              Use at least 12 characters.
            </span>
          </label>
          <fieldset className="admin-registry-assignment">
            <legend>
              Vehicle assignment <span className="admin-registry-optional">Optional</span>
            </legend>
            <p className="admin-registry-field-hint">
              Vehicles can be shared. Choose a registered vehicle, add one now, or leave this blank.
            </p>
            <div className="admin-registry-vehicle-modes">
              <label>
                <input
                  type="radio"
                  name="vehicleMode"
                  value="existing"
                  checked={employeeVehicleMode === 'existing'}
                  disabled={vehiclesLoading || !assignableVehicles.length}
                  onChange={() => {
                    setVehicleSelectionError('');
                    setEmployeeVehicleMode('existing');
                  }}
                />
                <span>Existing vehicle</span>
              </label>
              <label>
                <input
                  type="radio"
                  name="vehicleMode"
                  value="new"
                  checked={employeeVehicleMode === 'new'}
                  onChange={() => {
                    setVehicleSelectionError('');
                    setEmployeeVehicleMode('new');
                  }}
                />
                <span>New vehicle</span>
              </label>
              <label>
                <input
                  type="radio"
                  name="vehicleMode"
                  value="none"
                  checked={employeeVehicleMode === 'none'}
                  onChange={() => {
                    setVehicleSelectionError('');
                    setEmployeeVehicleMode('none');
                  }}
                />
                <span>No vehicle</span>
              </label>
            </div>
            {employeeVehicleMode === 'existing' && (
              <div className="admin-registry-dropdown-field">
                <span
                  className="admin-registry-label-line"
                  id="registryVehicleLabel"
                >
                  Registered vehicle{' '}
                  <span className="admin-registry-required">*</span>
                </span>
                <RegistryDropdown
                  id="registryVehicle"
                  name="vehicleId"
                  labelId="registryVehicleLabel"
                  value={selectedVehicleId}
                  options={vehicleOptions}
                  placeholder="Choose a registered vehicle"
                  required
                  disabled={vehiclesLoading || !assignableVehicles.length}
                  error={vehicleSelectionError}
                  onChange={(value) => {
                    setSelectedVehicleId(value);
                    setVehicleSelectionError('');
                  }}
                />
              </div>
            )}
            {!vehiclesLoading && !assignableVehicles.length && (
              <p className="admin-registry-field-hint">
                No vehicles are registered yet. Choose “New vehicle” or “No vehicle”.
              </p>
            )}
            {employeeVehicleMode === 'new' && (
              <>
                <label>
                  <span className="admin-registry-checkbox">
                    <input
                      name="vehicleIsCompany"
                      type="checkbox"
                      defaultChecked
                    />
                    <span>Counts toward the company fleet</span>
                  </span>
                  <span className="admin-registry-field-hint">
                    Leave unchecked for an employee’s personal vehicle.
                  </span>
                </label>
                <div className="admin-registry-vehicle-details">
                  <label>
                    <span className="admin-registry-label-line">
                      Make <span className="admin-registry-optional">Optional</span>
                    </span>
                    <input
                      name="vehicleMake"
                      maxLength="100"
                      autoComplete="off"
                    />
                  </label>
                  <label>
                    <span className="admin-registry-label-line">
                      Model <span className="admin-registry-optional">Optional</span>
                    </span>
                    <input
                      name="vehicleModel"
                      maxLength="100"
                      autoComplete="off"
                    />
                  </label>
                </div>
                <label>
                  <span className="admin-registry-label-line">
                    Fuel type <span className="admin-registry-optional">Optional</span>
                  </span>
                  <select name="vehicleFuelType" defaultValue="">
                    <option value="">Not set</option>
                    <option value="Diesel">Diesel</option>
                    <option value="AdBlue">AdBlue</option>
                    <option value="Petrol">Petrol</option>
                  </select>
                </label>
                <label>
                  <span className="admin-registry-label-line">
                    Tank capacity (L)
                    <span className="admin-registry-optional">Optional</span>
                  </span>
                  <input
                    name="vehicleTankCapacity"
                    type="number"
                    min="0.1"
                    step="0.1"
                  />
                </label>
                <label>
                  <span className="admin-registry-label-line">
                    NCT expiry date
                    <span className="admin-registry-optional">Optional</span>
                  </span>
                  <input name="nctExpiryDate" type="date" lang="en-IE" />
                </label>
                <label>
                  <span className="admin-registry-label-line">
                    Vehicle registration number{' '}
                    <span className="admin-registry-required">*</span>
                  </span>
                  <input
                    name="vehicleRegistrationNumber"
                    autoComplete="off"
                    maxLength="32"
                    required
                  />
                </label>
              </>
            )}
          </fieldset>
          <button
            className="primary-button"
            type="submit"
            disabled={vehiclesLoading}
          >
            {vehiclesLoading ? 'Loading vehicle options…' : 'Create employee account'}
          </button>
        </form>
        <form
          className="login-form admin-registry-form admin-registry-vehicle-form"
          onSubmit={handleAddVehicle}
          aria-labelledby="registryVehicleTitle"
        >
          <h4 id="registryVehicleTitle">Add vehicle</h4>
          <p className="admin-registry-help">
            Registration is required; fuel type, make, model, tank capacity, and NCT
            date are optional. A QR code is generated after saving.
          </p>
          <label>
            <span className="admin-registry-checkbox">
              <input
                name="isCompanyVehicle"
                type="checkbox"
                defaultChecked
              />
              <span>Counts toward the company fleet</span>
            </span>
            <span className="admin-registry-field-hint">
              Leave unchecked to register a personal vehicle.
            </span>
          </label>
          <div className="admin-registry-vehicle-details">
            <label>
              <span className="admin-registry-label-line">
                Make <span className="admin-registry-optional">Optional</span>
              </span>
              <input name="make" maxLength="100" autoComplete="off" />
            </label>
            <label>
              <span className="admin-registry-label-line">
                Model <span className="admin-registry-optional">Optional</span>
              </span>
              <input name="model" maxLength="100" autoComplete="off" />
            </label>
          </div>
          <label>
            <span className="admin-registry-label-line">
              Fuel type <span className="admin-registry-optional">Optional</span>
            </span>
            <select name="fuelType" defaultValue="">
              <option value="">Not set</option>
              <option value="Diesel">Diesel</option>
              <option value="AdBlue">AdBlue</option>
              <option value="Petrol">Petrol</option>
            </select>
          </label>
          <label>
            <span className="admin-registry-label-line">
              Tank capacity (L) <span className="admin-registry-optional">Optional</span>
            </span>
            <input
              name="tankCapacity"
              type="number"
              min="0.1"
              step="0.1"
            />
          </label>
          <label>
            <span className="admin-registry-label-line">
              NCT expiry date <span className="admin-registry-optional">Optional</span>
            </span>
            <input name="nctExpiryDate" type="date" lang="en-IE" />
          </label>
          <label>
            <span className="admin-registry-label-line">
              Registration number <span className="admin-registry-required">*</span>
            </span>
            <input
              name="registrationNumber"
              autoComplete="off"
              maxLength="32"
              required
            />
          </label>
          <button className="primary-button" type="submit">
            Add vehicle and generate QR
          </button>
        </form>
      </div>
      {qrProvision && (
        <div className="qr-provision" role="status">
          <div>
            <h4>QR code for {qrProvision.registrationNumber}</h4>
            <p>
              Print this code for the vehicle. The secret is only shown now; generating
              another code invalidates this one.
            </p>
            <QRCodeSVG value={qrProvision.qrPayload} size={192} />
          </div>
        </div>
      )}
    </section>
  );
}

function formatCost(value) {
  return new Intl.NumberFormat('en-IE', {
    style: 'currency',
    currency: 'EUR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(Number(value ?? 0));
}

function formatDateOnly(value) {
  return value
    ? new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium' }).format(
        new Date(`${value}T00:00:00`)
      )
    : '--';
}

function getCurrentMonthRange() {
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const toInputDate = (date) => {
    const month = `${date.getMonth() + 1}`.padStart(2, '0');
    const day = `${date.getDate()}`.padStart(2, '0');
    return `${date.getFullYear()}-${month}-${day}`;
  };
  return { startDate: toInputDate(monthStart), endDate: toInputDate(now) };
}

function AdminEmployeeRecordsTab({
  onDownload,
  onEmail,
  onExport
}) {
  const [employees, setEmployees] = useState([]);
  const [employeesLoading, setEmployeesLoading] = useState(true);
  const [employeesError, setEmployeesError] = useState('');
  const [employeeSearch, setEmployeeSearch] = useState('');
  const [employeeId, setEmployeeId] = useState('');
  const [employeePickerOpen, setEmployeePickerOpen] = useState(false);
  const [activeEmployeeOption, setActiveEmployeeOption] = useState(0);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [records, setRecords] = useState([]);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [recordsError, setRecordsError] = useState('');
  const [roleSelection, setRoleSelection] = useState('employee');
  const [roleSaving, setRoleSaving] = useState(false);
  const [roleError, setRoleError] = useState('');
  const [roleMessage, setRoleMessage] = useState('');
  const [statusSaving, setStatusSaving] = useState(false);
  const [statusError, setStatusError] = useState('');
  const [statusMessage, setStatusMessage] = useState('');
  const employeePickerRef = useRef(null);
  const employeeOptionRefs = useRef([]);
  const recordsRequestId = useRef(0);
  const selectedEmployee = employees.find(
    (employeeItem) => employeeItem.id === Number(employeeId)
  );
  const visibleEmployees = employees.filter((employeeItem) =>
    [
      employeeItem.name,
      employeeItem.email,
      employeeItem.username,
      employeeItem.role
    ]
      .filter(Boolean)
      .join(' ')
      .toLocaleLowerCase()
      .includes(employeeSearch.trim().toLocaleLowerCase())
  );

  useEffect(() => {
    if (!employeePickerOpen) return undefined;
    function dismissEmployeePicker(event) {
      if (!employeePickerRef.current?.contains(event.target)) {
        setEmployeePickerOpen(false);
      }
    }
    document.addEventListener('pointerdown', dismissEmployeePicker);
    return () => document.removeEventListener('pointerdown', dismissEmployeePicker);
  }, [employeePickerOpen]);

  useEffect(() => {
    if (employeePickerOpen) {
      employeeOptionRefs.current[activeEmployeeOption]?.scrollIntoView({
        block: 'nearest'
      });
    }
  }, [activeEmployeeOption, employeePickerOpen]);

  useEffect(() => {
    let active = true;
    getAdminEmployees()
      .then((result) => {
        if (active) setEmployees(result);
      })
      .catch((error) => {
        if (active) setEmployeesError(error.message);
      })
      .finally(() => {
        if (active) setEmployeesLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function loadEmployeeRecords(
    range = { startDate, endDate },
    requestedEmployeeId = employeeId
  ) {
    if (!requestedEmployeeId) {
      setRecordsError('Select an employee to view their fuel records.');
      return;
    }
    if (range.startDate && range.endDate && range.startDate > range.endDate) {
      setRecordsError('The start date must be on or before the end date.');
      return;
    }
    const requestId = ++recordsRequestId.current;
    setRecordsLoading(true);
    setRecordsError('');
    try {
      const result = await getAdminEmployeeFuelRecords(
        Number(requestedEmployeeId),
        range
      );
      if (requestId === recordsRequestId.current) setRecords(result);
    } catch (error) {
      if (requestId === recordsRequestId.current) {
        setRecordsError(error.message);
      }
    } finally {
      if (requestId === recordsRequestId.current) setRecordsLoading(false);
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    void loadEmployeeRecords();
  }

  function handleAllDates() {
    setStartDate('');
    setEndDate('');
    void loadEmployeeRecords({ startDate: '', endDate: '' });
  }

  function chooseEmployee(employeeItem) {
    setEmployeeId(String(employeeItem.id));
    setRoleSelection(employeeItem.role === 'boss' ? 'boss' : 'employee');
    setRoleError('');
    setRoleMessage('');
    setStatusError('');
    setStatusMessage('');
    setStartDate('');
    setEndDate('');
    setRecords([]);
    setRecordsError('');
    setEmployeePickerOpen(false);
    void loadEmployeeRecords(
      { startDate: '', endDate: '' },
      employeeItem.id
    );
  }

  async function handleRoleUpdate(event) {
    event.preventDefault();
    if (!selectedEmployee || selectedEmployee.role === 'admin') return;
    setRoleSaving(true);
    setRoleError('');
    setRoleMessage('');
    try {
      const updatedEmployee = await updateEmployeeRole(
        selectedEmployee.id,
        roleSelection
      );
      setEmployees((current) =>
        current.map((item) =>
          item.id === updatedEmployee.id ? updatedEmployee : item
        )
      );
      setRoleMessage(
        `${updatedEmployee.name}'s role is now ${
          updatedEmployee.role === 'boss' ? 'Boss' : 'Employee'
        }.`
      );
    } catch (error) {
      setRoleError(error.message);
    } finally {
      setRoleSaving(false);
    }
  }

  async function handleStatusToggle() {
    if (!selectedEmployee || selectedEmployee.role === 'admin') return;
    const nextIsActive = !selectedEmployee.isActive;
    if (
      !nextIsActive &&
      !window.confirm(
        `Deactivate ${selectedEmployee.name}? This revokes sessions and prevents sign-in. Their fuel history will be kept.`
      )
    ) {
      return;
    }
    setStatusSaving(true);
    setStatusError('');
    setStatusMessage('');
    try {
      const updatedEmployee = await updateEmployeeStatus(
        selectedEmployee.id,
        nextIsActive
      );
      setEmployees((current) =>
        current.map((item) =>
          item.id === updatedEmployee.id ? updatedEmployee : item
        )
      );
      setStatusMessage(
        `${updatedEmployee.name} account ${
          updatedEmployee.isActive ? 'reactivated' : 'deactivated'
        }; fuel history retained.`
      );
    } catch (error) {
      setStatusError(error.message);
    } finally {
      setStatusSaving(false);
    }
  }

  function handleEmployeePickerKeyDown(event) {
    if (!employeePickerOpen) {
      if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        const selectedIndex = visibleEmployees.findIndex(
          (employeeItem) => employeeItem.id === Number(employeeId)
        );
        setActiveEmployeeOption(Math.max(selectedIndex, 0));
        setEmployeePickerOpen(true);
      }
      return;
    }

    if (event.key === 'Escape') {
      event.preventDefault();
      setEmployeePickerOpen(false);
      return;
    }
    if (!visibleEmployees.length) return;

    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      setActiveEmployeeOption((current) =>
        (current + direction + visibleEmployees.length) % visibleEmployees.length
      );
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      setActiveEmployeeOption(event.key === 'Home' ? 0 : visibleEmployees.length - 1);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      chooseEmployee(visibleEmployees[activeEmployeeOption]);
    }
  }

  return (
    <section
      className="admin-tab-panel admin-employee-records-tab"
      aria-labelledby="adminEmployeesTitle"
    >
      <header className="admin-tab-heading admin-employee-heading">
        <div className="admin-employee-heading-copy">
          <span className="admin-employee-heading-icon" aria-hidden="true">
            <AppIcon name="team" size={21} />
          </span>
          <div>
            <p className="eyebrow">PEOPLE &amp; FUEL ACTIVITY</p>
            <h3 id="adminEmployeesTitle">Employee records</h3>
            <p>Select an employee to load their complete fuel history; dates can narrow the results.</p>
          </div>
        </div>
        <span className="admin-employee-count" role="status" aria-live="polite">
          {employeesLoading
            ? 'Loading employees...'
            : `${visibleEmployees.length} shown · ${employees.length} total`}
        </span>
      </header>
      <form className="admin-filter-form" onSubmit={handleSubmit}>
        <label>
          Search employees
          <input
            type="search"
            value={employeeSearch}
            placeholder="Name, email or username"
            onFocus={() => setEmployeePickerOpen(true)}
            onChange={(event) => {
              setEmployeeSearch(event.target.value);
              setEmployeeId('');
              recordsRequestId.current += 1;
              setRecordsLoading(false);
              setRecords([]);
              setRecordsError('');
              setActiveEmployeeOption(0);
              setEmployeePickerOpen(true);
            }}
          />
        </label>
        <div className="admin-employee-picker-field">
          <span className="admin-employee-picker-label" id="adminEmployeePickerLabel">
            Employee
          </span>
          <div className="admin-employee-picker" ref={employeePickerRef}>
            <button
              className={`admin-employee-picker-trigger${employeePickerOpen ? ' is-open' : ''}`}
              type="button"
              role="combobox"
              aria-labelledby="adminEmployeePickerLabel adminEmployeePickerValue"
              aria-required="true"
              aria-haspopup="listbox"
              aria-expanded={employeePickerOpen}
              aria-controls="adminEmployeeOptions"
              aria-activedescendant={
                employeePickerOpen && visibleEmployees[activeEmployeeOption]
                  ? `adminEmployeeOption-${visibleEmployees[activeEmployeeOption].id}`
                  : undefined
              }
              disabled={employeesLoading}
              onClick={() => {
                const selectedIndex = visibleEmployees.findIndex(
                  (employeeItem) => employeeItem.id === Number(employeeId)
                );
                setActiveEmployeeOption(Math.max(selectedIndex, 0));
                setEmployeePickerOpen((open) => !open);
              }}
              onKeyDown={handleEmployeePickerKeyDown}
            >
              <span className={`admin-picker-avatar${selectedEmployee ? '' : ' is-placeholder'}`}>
                {selectedEmployee
                  ? selectedEmployee.name.trim().charAt(0).toUpperCase() || '?'
                  : <AppIcon name="team" size={16} />}
              </span>
              <span className="admin-picker-value">
                <strong id="adminEmployeePickerValue">
                  {selectedEmployee?.name ??
                    (employeesLoading ? 'Loading employees...' : 'Choose an employee')}
                </strong>
                <small>
                  {selectedEmployee
                    ? selectedEmployee.email || selectedEmployee.username || selectedEmployee.role
                    : `${visibleEmployees.length} employees available`}
                </small>
              </span>
              <span className="admin-picker-chevron" aria-hidden="true" />
            </button>
            {employeePickerOpen && (
              <div
                className="admin-employee-picker-menu"
                id="adminEmployeeOptions"
                role="listbox"
                aria-label="Employees"
              >
                {visibleEmployees.length ? visibleEmployees.map((employeeItem, index) => {
                  const isSelected = employeeItem.id === Number(employeeId);
                  const isActive = index === activeEmployeeOption;
                  return (
                    <div
                      className={`admin-employee-option${isActive ? ' is-active' : ''}${isSelected ? ' is-selected' : ''}`}
                      id={`adminEmployeeOption-${employeeItem.id}`}
                      key={employeeItem.id}
                      ref={(element) => {
                        employeeOptionRefs.current[index] = element;
                      }}
                      role="option"
                      aria-selected={isSelected}
                      onMouseEnter={() => setActiveEmployeeOption(index)}
                      onClick={() => chooseEmployee(employeeItem)}
                    >
                      <span className="admin-picker-avatar">
                        {employeeItem.name.trim().charAt(0).toUpperCase() || '?'}
                      </span>
                      <span className="admin-picker-value">
                        <strong>{employeeItem.name}</strong>
                        <small>
                          {employeeItem.username || employeeItem.email || 'No contact details'}
                        </small>
                      </span>
                      <span className="admin-employee-option-meta">
                        <span className="admin-picker-role">{employeeItem.role}</span>
                        {!employeeItem.isActive && (
                          <span className="admin-picker-inactive">Inactive</span>
                        )}
                      </span>
                      {isSelected && <AppIcon name="check" size={15} />}
                    </div>
                  );
                }) : (
                  <p className="admin-employee-picker-empty">
                    No employees match this search.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
        <label>
          From
          <input
            type="date"
            value={startDate}
            onChange={(event) => setStartDate(event.target.value)}
          />
        </label>
        <label>
          To
          <input
            type="date"
            value={endDate}
            onChange={(event) => setEndDate(event.target.value)}
          />
        </label>
        <div className="admin-filter-actions">
          <button className="primary-button" type="submit" disabled={!employeeId}>
            Find records
          </button>
          <button
            className="outline-button"
            type="button"
            onClick={handleAllDates}
            disabled={!employeeId}
          >
            All dates
          </button>
        </div>
      </form>
      {employeesError && <p className="auth-error" role="alert">{employeesError}</p>}
      {recordsError && <p className="auth-error" role="alert">{recordsError}</p>}
      {selectedEmployee && (
        <div className="admin-selected-employee" aria-label="Selected employee">
          <span className="admin-selected-avatar" aria-hidden="true">
            {selectedEmployee.name.trim().charAt(0).toUpperCase() || '?'}
          </span>
          <span className="admin-selected-identity">
            <strong>{selectedEmployee.name}</strong>
            <small>
              {selectedEmployee.email || selectedEmployee.username || 'No contact details'}
            </small>
          </span>
          <span className="admin-employee-role">{selectedEmployee.role}</span>
          <span
            className={`admin-employee-status${selectedEmployee.isActive ? '' : ' is-inactive'}`}
          >
            <span aria-hidden="true" />
            {selectedEmployee.isActive ? 'Active' : 'Inactive'}
          </span>
        </div>
      )}
      {selectedEmployee && selectedEmployee.role !== 'admin' && (
        <>
          <form className="admin-role-form" onSubmit={handleRoleUpdate}>
            <div>
              <h4>Access level</h4>
              <p>
                Choose Employee or Boss access. Changes apply the next time
                this account signs in.
              </p>
            </div>
            <label htmlFor="adminEmployeeRole">Account role</label>
            <select
              id="adminEmployeeRole"
              value={roleSelection}
              onChange={(event) => {
                setRoleSelection(event.target.value);
                setRoleError('');
                setRoleMessage('');
              }}
              disabled={roleSaving}
            >
              <option value="employee">Employee</option>
              <option value="boss">Boss</option>
            </select>
            <button
              className="primary-button"
              type="submit"
              disabled={roleSaving || roleSelection === selectedEmployee.role}
            >
              {roleSaving ? 'Saving…' : 'Save role'}
            </button>
            {roleError && <p className="auth-error" role="alert">{roleError}</p>}
            {roleMessage && (
              <p className="admin-role-success" role="status">{roleMessage}</p>
            )}
          </form>
          <div className="admin-role-form">
            <div>
              <h4>Account status</h4>
              <p>
                Deactivating blocks sign-in and ends active sessions. Fuel
                history is kept.
              </p>
            </div>
            <button
              className={`outline-button admin-account-status-button${
                selectedEmployee.isActive ? ' is-active' : ''
              }`}
              type="button"
              onClick={() => void handleStatusToggle()}
              disabled={statusSaving}
            >
              {statusSaving
                ? 'Saving status…'
                : selectedEmployee.isActive
                  ? 'Deactivate account'
                  : 'Reactivate account'}
            </button>
            {statusError && (
              <p className="auth-error" role="alert">{statusError}</p>
            )}
            {statusMessage && (
              <p className="admin-role-success" role="status">{statusMessage}</p>
            )}
          </div>
        </>
      )}
      {employeeId ? (
        <HistorySection
          id="adminEmployeeHistory"
          eyebrow="FILTERED FUEL HISTORY"
          title={
            selectedEmployee
              ? `Fills submitted by ${selectedEmployee.name}`
              : 'Employee filling actions'
          }
          records={records}
          loading={recordsLoading}
          onDownload={onDownload}
          onEmail={onEmail}
          onExport={onExport}
          showMeterPhoto
        />
      ) : (
        <div className="empty-state admin-employee-empty">
          <span className="admin-employee-empty-icon" aria-hidden="true">
            <AppIcon name="history" size={20} />
          </span>
          <h4>Select an employee to begin</h4>
          <p>Choose an account to load all dates, or use the date filters to narrow its fuel history.</p>
        </div>
      )}
    </section>
  );
}

function AdminSummaryTab({
  globalMeter,
  globalMeterHistory,
  loading,
  onOpenNct,
  onOpenEmployeeRecords,
  onGlobalMeterEventCreated
}) {
  const initialRange = getCurrentMonthRange();
  const [startDate, setStartDate] = useState(initialRange.startDate);
  const [endDate, setEndDate] = useState(initialRange.endDate);
  const [summary, setSummary] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryRefreshing, setSummaryRefreshing] = useState(false);
  const [summaryError, setSummaryError] = useState('');
  const [summaryLastUpdated, setSummaryLastUpdated] = useState(null);
  const [cleanupOpen, setCleanupOpen] = useState(false);
  const [cleanupConfirmation, setCleanupConfirmation] = useState('');
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [cleanupError, setCleanupError] = useState('');
  const summaryRangeRef = useRef(initialRange);
  const summaryRequestIdRef = useRef(0);

  async function loadSummary(range, { background = false } = {}) {
    if (
      range.startDate &&
      range.endDate &&
      range.startDate > range.endDate
    ) {
      setSummaryError('The start date must be on or before the end date.');
      return;
    }
    summaryRangeRef.current = range;
    const requestId = ++summaryRequestIdRef.current;
    if (background) {
      setSummaryRefreshing(true);
    } else {
      setSummaryLoading(true);
    }
    setSummaryError('');
    try {
      const result = await getAdminFuelSummary(range);
      if (requestId === summaryRequestIdRef.current) {
        setSummary(result);
        setSummaryLastUpdated(new Date());
      }
    } catch (error) {
      if (requestId === summaryRequestIdRef.current) {
        setSummaryError(error.message);
      }
    } finally {
      if (requestId === summaryRequestIdRef.current) {
        setSummaryLoading(false);
        setSummaryRefreshing(false);
      }
    }
  }

  useEffect(() => {
    void loadSummary(initialRange);
    const refreshVisibleSummary = () => {
      if (document.visibilityState === 'visible') {
        void loadSummary(summaryRangeRef.current, { background: true });
      }
    };
    const refreshInterval = window.setInterval(
      refreshVisibleSummary,
      15_000
    );
    window.addEventListener('focus', refreshVisibleSummary);
    document.addEventListener('visibilitychange', refreshVisibleSummary);
    return () => {
      window.clearInterval(refreshInterval);
      window.removeEventListener('focus', refreshVisibleSummary);
      document.removeEventListener('visibilitychange', refreshVisibleSummary);
      summaryRequestIdRef.current += 1;
    };
  }, []);

  function handleSubmit(event) {
    event.preventDefault();
    void loadSummary({ startDate, endDate });
  }

  function handleAllDates() {
    setStartDate('');
    setEndDate('');
    void loadSummary({ startDate: '', endDate: '' });
  }

  async function handleOperationalDataClear(event) {
    event.preventDefault();
    if (cleanupConfirmation !== 'CLEAR OPERATIONAL DATA') return;

    setCleanupLoading(true);
    setCleanupError('');
    try {
      await clearAdminOperationalData(cleanupConfirmation);
      window.location.reload();
    } catch (error) {
      setCleanupError(error.message);
      setCleanupLoading(false);
    }
  }

  const selectedPeriod =
    summary?.startDate || summary?.endDate
      ? `${summary.startDate ? formatDateOnly(summary.startDate) : 'Beginning'} - ${
          summary.endDate ? formatDateOnly(summary.endDate) : 'Latest'
        }`
      : 'All available dates';

  return (
    <div className="admin-summary-tab">
      <GlobalMeterDashboard
        summary={globalMeter}
        history={globalMeterHistory}
        loading={loading}
        onRecordEvent={onGlobalMeterEventCreated}
        onOpenNct={onOpenNct}
      />
      <section className="admin-tab-panel" aria-labelledby="adminSummaryTitle">
        <header className="admin-tab-heading">
          <div>
            <p className="eyebrow">FLEET SUMMARY</p>
            <h3 id="adminSummaryTitle">Fuel activity and spending</h3>
            <p>Filter fleet fuel fills and recorded costs by date range.</p>
          </div>
          <span className="management-only-badge">ADMIN ONLY</span>
        </header>

        <form className="admin-filter-form" onSubmit={handleSubmit}>
          <label>
            From
            <input
              type="date"
              value={startDate}
              min={summary?.availableFrom ?? undefined}
              max={summary?.availableTo ?? undefined}
              onChange={(event) => setStartDate(event.target.value)}
            />
          </label>
          <label>
            To
            <input
              type="date"
              value={endDate}
              min={summary?.availableFrom ?? undefined}
              max={summary?.availableTo ?? undefined}
              onChange={(event) => setEndDate(event.target.value)}
            />
          </label>
          <div className="admin-filter-actions">
            <button className="primary-button" type="submit">
              Apply date range
            </button>
            <button
              className="outline-button"
              type="button"
              disabled={summaryLoading || summaryRefreshing}
              onClick={() =>
                void loadSummary(summaryRangeRef.current, { background: true })
              }
            >
              {summaryRefreshing ? 'Refreshing...' : 'Refresh summary'}
            </button>
            <button
              className="outline-button"
              type="button"
              onClick={handleAllDates}
            >
              All available dates
            </button>
          </div>
        </form>

        {summaryError && <p className="auth-error" role="alert">{summaryError}</p>}
        {summary?.availableFrom && summary?.availableTo && (
          <p className="admin-available-dates">
            Available records: {formatDateOnly(summary.availableFrom)} to{' '}
            {formatDateOnly(summary.availableTo)}. Showing: {selectedPeriod}.
            {summaryLastUpdated && (
              <> Last updated {summaryLastUpdated.toLocaleTimeString()}.</>
            )}
          </p>
        )}

        {summaryLoading ? (
          <p className="global-meter-empty" role="status">Calculating fleet summary...</p>
        ) : summary ? (
          <>
            <div className="admin-summary-metrics">
              <article className="admin-summary-metric">
                <span>FILLS IN SELECTED PERIOD</span>
                <strong>{summary.fillCount.toLocaleString()}</strong>
                <small>{selectedPeriod}</small>
              </article>
              <article className="admin-summary-metric">
                <span>FUEL FILLED</span>
                <strong>{formatLitres(summary.totalFillLitres)} <i>L</i></strong>
                <small>Across all vehicles</small>
              </article>
              <article className="admin-summary-metric">
                <span>RECORDED FUEL COST (EUR)</span>
                <strong>{formatCost(summary.totalCost)}</strong>
                <small>
                  {summary.costRecordCount
                    ? `From ${summary.costRecordCount} fills with costs recorded; shown in EUR.`
                    : 'No cost data recorded for this period.'}
                </small>
              </article>
            </div>
            <section className="admin-top-vehicles">
              <div>
                <p className="eyebrow">TOP 4 / SELECTED PERIOD</p>
                <h4>Vehicles by fuel volume</h4>
              </div>
              {summary.topVehicles.length ? (
                <ol>
                  {summary.topVehicles.slice(0, 4).map((item, index) => (
                    <li key={`${item.vehicleId ?? item.registrationNumber}`}>
                      <span className="admin-vehicle-rank">
                        {`${index + 1}`.padStart(2, '0')}
                      </span>
                      <strong>{item.registrationNumber}</strong>
                      <span>{item.fillCount} fills</span>
                      <b>{formatLitres(item.totalFillLitres)} L</b>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="global-meter-empty">
                  No vehicle fills were recorded for this period.
                </p>
              )}
            </section>
            <section
              className="admin-recent-records"
              aria-labelledby="adminRecentRecordsTitle"
            >
              <header className="admin-recent-records-heading">
                <div>
                  <p className="eyebrow">LATEST ACCEPTED ENTRIES</p>
                  <h4 id="adminRecentRecordsTitle">Recent fuel records</h4>
                  <p>
                    Manual, OCR, and calculated fills in the selected date range.
                    Refreshes automatically every 15 seconds.
                  </p>
                </div>
                <button
                  className="outline-button"
                  type="button"
                  onClick={onOpenEmployeeRecords}
                >
                  Browse employee records
                </button>
              </header>
              {summary.recentRecords.length ? (
                <div className="admin-recent-records-table-wrap" role="region" aria-label="Recent fuel records" tabIndex="0">
                  <table className="admin-recent-records-table">
                    <thead>
                      <tr>
                        <th scope="col">Date</th>
                        <th scope="col">Employee</th>
                        <th scope="col">Vehicle</th>
                        <th scope="col">Fill</th>
                        <th scope="col">Top-row evidence</th>
                        <th scope="col">Top difference</th>
                        <th scope="col">Mileage</th>
                        <th scope="col">Previous total</th>
                        <th scope="col">Global total</th>
                        <th scope="col">Fill source</th>
                        <th scope="col">Reading source</th>
                        <th scope="col">Verification</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.recentRecords.map((record) => (
                        <tr key={record.id}>
                          <td>{formatDate(record.createdAt)}</td>
                          <td>{record.employeeName}</td>
                          <td>{record.regNumber}</td>
                          <td>{formatLitres(record.currentFillLitres)} L</td>
                          <td>
                            {record.topCurrentFillMilliLitres == null
                              ? 'Missing'
                              : `${(record.topCurrentFillMilliLitres / 1000).toFixed(3)} L`}
                          </td>
                          <td>
                            {record.topCurrentFillMilliLitres == null
                              ? '—'
                              : record.currentFillMilliLitres == null
                                ? '—'
                                : `${((record.topCurrentFillMilliLitres - record.currentFillMilliLitres) / 1000).toFixed(3)} L`}
                          </td>
                          <td>{formatMileage(record.mileageMiles)} mi</td>
                          <td>
                            {record.previousGlobalTotalInteger == null
                              ? '—'
                              : `${formatMilliLitres(record.previousGlobalTotalInteger)} L`}
                          </td>
                          <td>
                            {record.cumulativeTotalInteger == null
                              ? '—'
                              : `${formatMilliLitres(record.cumulativeTotalInteger)} L`}
                          </td>
                          <td>
                            <span
                              className={`admin-record-source admin-record-source--${record.meterReadingSource}`}
                            >
                              {record.meterReadingSource}
                            </span>
                          </td>
                          <td>{record.readingSource || 'legacy'}</td>
                          <td>
                            <span
                              className={`admin-record-source admin-record-source--${record.meterCheckStatus}`}
                            >
                              {record.meterCheckStatus}
                            </span>
                            {record.meterWarnings?.length > 0 && (
                              <details>
                                <summary>Warnings ({record.meterWarnings.length})</summary>
                                <ul>
                                  {record.meterWarnings.map((warning) => (
                                    <li key={warning}>{warning}</li>
                                  ))}
                                </ul>
                              </details>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="admin-recent-records-empty">
                  No fuel records were found for this date range.
                </p>
              )}
            </section>
          </>
        ) : null}
      </section>
      <section
        className="admin-data-cleanup"
        aria-labelledby="adminDataCleanupTitle"
      >
        <div>
          <p className="eyebrow">DANGER ZONE</p>
          <h3 id="adminDataCleanupTitle">Clear operational data</h3>
          <p>
            Permanently remove all fuel entries, mileage history, meter
            readings, reviews, corrections, and meter photos. All user accounts
            and vehicles will be kept.
          </p>
        </div>
        {!cleanupOpen ? (
          <button
            className="danger-button"
            type="button"
            onClick={() => setCleanupOpen(true)}
          >
            Clean operational data
          </button>
        ) : (
          <form onSubmit={handleOperationalDataClear}>
            <label htmlFor="adminDataCleanupConfirmation">
              To confirm, type <strong>CLEAR OPERATIONAL DATA</strong>
              <input
                id="adminDataCleanupConfirmation"
                autoComplete="off"
                value={cleanupConfirmation}
                onChange={(event) =>
                  setCleanupConfirmation(event.target.value)
                }
                disabled={cleanupLoading}
              />
            </label>
            <div className="admin-data-cleanup-actions">
              <button
                className="danger-button"
                type="submit"
                disabled={
                  cleanupLoading ||
                  cleanupConfirmation !== 'CLEAR OPERATIONAL DATA'
                }
              >
                {cleanupLoading ? 'Cleaning data...' : 'Permanently clear data'}
              </button>
              <button
                className="outline-button"
                type="button"
                disabled={cleanupLoading}
                onClick={() => {
                  setCleanupOpen(false);
                  setCleanupConfirmation('');
                  setCleanupError('');
                }}
              >
                Cancel
              </button>
            </div>
            {cleanupError && (
              <p className="auth-error" role="alert">{cleanupError}</p>
            )}
          </form>
        )}
      </section>
    </div>
  );
}

function formatIrishDate(value) {
  if (!value) return 'NCT date not set';
  return new Intl.DateTimeFormat('en-IE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'UTC'
  }).format(new Date(`${value}T00:00:00Z`));
}

function parseIrishDate(value) {
  const trimmedValue = value.trim();
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(trimmedValue);
  if (!match) return trimmedValue === '' ? null : undefined;

  const [, dayText, monthText, yearText] = match;
  const day = Number(dayText);
  const month = Number(monthText);
  const year = Number(yearText);
  if (year < 1000) return undefined;

  const parsedDate = new Date(Date.UTC(year, month - 1, day));
  if (
    parsedDate.getUTCFullYear() !== year ||
    parsedDate.getUTCMonth() !== month - 1 ||
    parsedDate.getUTCDate() !== day
  ) {
    return undefined;
  }
  return `${yearText}-${monthText}-${dayText}`;
}

function nctStatusLabel(status) {
  return {
    upcoming: 'Upcoming',
    urgent: 'Urgent',
    expires_today: 'Expires today',
    expired: 'Expired',
    no_alert: 'No alert',
    not_set: 'NCT date not set'
  }[status] ?? status;
}

function nctDaysLabel(item) {
  if (item.daysRemaining == null) return 'Date not set';
  if (item.daysRemaining < 0) {
    const overdue = Math.abs(item.daysRemaining);
    return `${overdue} day${overdue === 1 ? '' : 's'} overdue`;
  }
  if (item.daysRemaining === 0) return 'Today';
  return `${item.daysRemaining} day${item.daysRemaining === 1 ? '' : 's'} left`;
}

function NctAlertsCard({ onOpen }) {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    const loadAlerts = async () => {
      try {
        const result = await getNctAlerts();
        if (active) {
          setSummary(result);
          setError('');
        }
      } catch (requestError) {
        if (active) setError(requestError.message);
      }
    };
    void loadAlerts();
    const refreshId = window.setInterval(() => void loadAlerts(), 60_000);
    return () => {
      active = false;
      window.clearInterval(refreshId);
    };
  }, []);

  const expiredCount = summary?.expiredCount ?? 0;
  const expiringSoonCount = summary?.expiringSoonCount ?? 0;
  const alertCount = summary?.alerts?.length ?? 0;
  const reminderMessage = error
    ? `NCT reminder unavailable: ${error}`
    : !summary
      ? 'Checking vehicle NCT dates...'
      : expiredCount > 0 || expiringSoonCount > 0
        ? [
            expiredCount > 0 ? `${expiredCount} expired` : null,
            expiringSoonCount > 0 ? `${expiringSoonCount} due within 30 days` : null
          ].filter(Boolean).join(' / ')
        : alertCount > 0
          ? `${alertCount} vehicle${alertCount === 1 ? '' : 's'} need an NCT check.`
          : 'No vehicles are currently due or overdue.';

  return (
    <button
      className="nct-expiry-reminder nct-expiry-reminder-compact"
      type="button"
      onClick={onOpen}
      aria-label={`NCT expiry reminder. ${reminderMessage} Open expiry monitoring.`}
    >
      <span className="nct-expiry-icon" aria-hidden="true">!</span>
      <span className="nct-expiry-copy">
        <span className="nct-expiry-eyebrow">VEHICLE COMPLIANCE</span>
        <span className="nct-expiry-title">NCT expiry reminder</span>
        <span
          className={`nct-expiry-message${error ? ' is-error' : ''}`}
          role={error ? 'alert' : undefined}
        >
          {reminderMessage}
        </span>
      </span>
      <span className="nct-expiry-action">
        View expiry monitoring <span aria-hidden="true">-&gt;</span>
      </span>
    </button>
  );
}

function NctMonitoring() {
  const [vehicles, setVehicles] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [searchQuery, setSearchQuery] = useState('');
  const [loadingNct, setLoadingNct] = useState(true);
  const [savingVehicleId, setSavingVehicleId] = useState(null);
  const [error, setError] = useState('');
  const [saveMessage, setSaveMessage] = useState('');

  useEffect(() => {
    let active = true;
    const loadVehicles = async () => {
      try {
        const items = await getVehicleNctList();
        if (active) {
          setVehicles(items);
          setError('');
        }
      } catch (requestError) {
        if (active) setError(requestError.message);
      } finally {
        if (active) setLoadingNct(false);
      }
    };
    void loadVehicles();
    const refreshId = window.setInterval(() => void loadVehicles(), 60_000);
    return () => {
      active = false;
      window.clearInterval(refreshId);
    };
  }, []);

  async function saveExpiry(vehicleId, expiryDate) {
    const current = vehicles.find((item) => item.vehicleId === vehicleId);
    if (!current) return;
    setSavingVehicleId(vehicleId);
    setError('');
    setSaveMessage('');
    try {
      const updated = await updateVehicleNct(vehicleId, expiryDate || null);
      setVehicles((items) =>
        items.map((item) => item.vehicleId === vehicleId ? updated : item)
      );
      setDrafts((items) => {
        const next = { ...items };
        delete next[vehicleId];
        return next;
      });
      setSaveMessage(`${updated.registrationNumber} NCT date updated.`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSavingVehicleId(null);
    }
  }

  function saveExpiryDraft(item) {
    const dateText =
      drafts[item.vehicleId] ??
      (item.nctExpiryDate ? formatIrishDate(item.nctExpiryDate) : '');
    const expiryDate = parseIrishDate(dateText);
    if (expiryDate === undefined) {
      setError('Enter a valid NCT date in DD/MM/YYYY format.');
      return;
    }
    if ((expiryDate || null) === (item.nctExpiryDate ?? null)) return;
    void saveExpiry(item.vehicleId, expiryDate);
  }

  const expiringCount = vehicles.filter(
    (item) => item.daysRemaining != null &&
      item.daysRemaining >= 0 && item.daysRemaining <= 30
  ).length;
  const expiredCount = vehicles.filter((item) => item.status === 'expired').length;
  const alertsCount = vehicles.filter((item) =>
    ['upcoming', 'urgent', 'expires_today', 'expired'].includes(item.status)
  ).length;
  const nearestVehicles = vehicles
    .filter((item) => item.nctExpiryDate && item.daysRemaining != null)
    .sort((first, second) =>
      Math.abs(first.daysRemaining) - Math.abs(second.daysRemaining) ||
      first.daysRemaining - second.daysRemaining ||
      first.registrationNumber.localeCompare(second.registrationNumber)
    )
    .slice(0, 7);
  const normalizedSearch = searchQuery.trim().toLowerCase();
  const filteredVehicles = vehicles.filter((item) =>
    [
      item.registrationNumber,
      item.make,
      item.model,
      item.employeeName,
      item.nctExpiryDate,
      nctStatusLabel(item.status)
    ]
      .filter(Boolean)
      .some((value) => value.toLowerCase().includes(normalizedSearch))
  );

  return (
    <section className="nct-monitoring" aria-labelledby="nctMonitoringTitle">
      <header className="nct-monitoring-heading">
        <div>
          <p className="eyebrow">VEHICLE COMPLIANCE</p>
          <h3 id="nctMonitoringTitle">NCT Expiry Monitoring</h3>
          <p>Irish date format · alerts refresh automatically · no duplicate alerts are stored</p>
        </div>
        <span className="management-only-badge">MANAGEMENT</span>
      </header>
      <div className="nct-summary-metrics">
        <article><span>EXPIRING WITHIN 30 DAYS</span><strong>{expiringCount}</strong></article>
        <article className={expiredCount ? 'is-expired' : ''}><span>EXPIRED</span><strong>{expiredCount}</strong></article>
        <article><span>ACTIVE ALERTS</span><strong>{alertsCount}</strong></article>
      </div>
      {error && <p className="nct-error" role="alert">{error}</p>}
      {saveMessage && <p className="nct-save-message" role="status">{saveMessage}</p>}
      {loadingNct ? (
        <p className="nct-empty" role="status">Loading registered vehicle NCT dates…</p>
      ) : vehicles.length === 0 ? (
        <p className="nct-empty">No registered vehicles were found.</p>
      ) : (
        <>
          <section className="nct-nearest-section" aria-labelledby="nctNearestTitle">
            <header className="nct-subsection-heading">
              <div>
                <p className="eyebrow">PRIORITY VIEW</p>
                <h4 id="nctNearestTitle">7 closest NCT dates</h4>
                <p>Nearest expiry dates first, including recently expired vehicles.</p>
              </div>
              <span>{nearestVehicles.length} vehicle{nearestVehicles.length === 1 ? '' : 's'}</span>
            </header>
            {nearestVehicles.length ? (
              <ul className="nct-nearest-grid">
                {nearestVehicles.map((item) => (
                  <li key={item.vehicleId}>
                    <button
                      className={`nct-nearest-card nct-nearest-${item.status}`}
                      type="button"
                      onClick={() => setSearchQuery(item.registrationNumber)}
                      aria-label={`Find ${item.registrationNumber} in the vehicle list`}
                    >
                      <span className="nct-nearest-card-top">
                        <strong>{item.registrationNumber}</strong>
                        <span className={`nct-status-badge nct-status-${item.status}`}>
                          {nctStatusLabel(item.status)}
                        </span>
                      </span>
                      <span className="nct-nearest-vehicle">
                        {[item.make, item.model].filter(Boolean).join(' ') || 'Vehicle details not set'}
                      </span>
                      <span className="nct-nearest-meta">
                        <span>{item.employeeName || 'Unassigned'}</span>
                        <time>{formatIrishDate(item.nctExpiryDate)}</time>
                      </span>
                      <span className="nct-nearest-days">{nctDaysLabel(item)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="nct-empty">No vehicles have an NCT expiry date yet.</p>
            )}
          </section>

          <div className="nct-vehicle-search">
            <label htmlFor="nctVehicleSearch">Find a vehicle</label>
            <div className="nct-search-control">
              <input
                id="nctVehicleSearch"
                type="search"
                placeholder="Registration, make, model, employee or status"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
              {searchQuery && (
                <button type="button" onClick={() => setSearchQuery('')}>
                  Clear
                </button>
              )}
            </div>
          </div>

          {normalizedSearch ? (
            filteredVehicles.length ? (
            <div className="nct-table-wrap">
              <table className="nct-table">
                <thead>
                  <tr>
                    <th scope="col">Vehicle</th>
                    <th scope="col">Assigned employee</th>
                    <th scope="col">NCT expiry</th>
                    <th scope="col">Time remaining</th>
                    <th scope="col">Status</th>
                    <th scope="col"><span className="visually-hidden">Save NCT date</span></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredVehicles.map((item) => (
                    <tr key={item.vehicleId}>
                      <td>
                        <strong>{item.registrationNumber}</strong>
                        <small>{[item.make, item.model].filter(Boolean).join(' ') || 'Vehicle details not set'}</small>
                      </td>
                      <td>{item.employeeName || 'Unassigned'}</td>
                      <td>
                        <div className="nct-date-editor">
                          <input
                            type="text"
                            inputMode="numeric"
                            maxLength={10}
                            placeholder={item.nctExpiryDate ? 'DD/MM/YYYY' : 'NCT date not set'}
                            aria-label={`NCT expiry date for ${item.registrationNumber}, DD/MM/YYYY`}
                            value={
                              drafts[item.vehicleId] ??
                              (item.nctExpiryDate ? formatIrishDate(item.nctExpiryDate) : '')
                            }
                            onChange={(event) => {
                              setDrafts((current) => ({
                                ...current,
                                [item.vehicleId]: event.target.value
                              }));
                              setSaveMessage('');
                              setError('');
                            }}
                          />
                        </div>
                      </td>
                      <td>{nctDaysLabel(item)}</td>
                      <td>
                        <span className={`nct-status-badge nct-status-${item.status}`}>
                          {nctStatusLabel(item.status)}
                        </span>
                      </td>
                      <td>
                        <button
                          className="nct-save-button"
                          type="button"
                          onClick={() => saveExpiryDraft(item)}
                          disabled={
                            savingVehicleId === item.vehicleId ||
                            (drafts[item.vehicleId] ??
                              (item.nctExpiryDate ? formatIrishDate(item.nctExpiryDate) : '')) ===
                              (item.nctExpiryDate ? formatIrishDate(item.nctExpiryDate) : '')
                          }
                        >
                          {savingVehicleId === item.vehicleId ? 'Saving…' : 'Save'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="nct-empty">No vehicles match “{searchQuery}”. Try a registration or employee name.</p>
            )
          ) : null}
        </>
      )}
    </section>
  );
}

function AdminMeterReadingReviews() {
  const [reviews, setReviews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingError, setLoadingError] = useState('');
  const [reviewNotes, setReviewNotes] = useState({});
  const [savingId, setSavingId] = useState(null);
  const [savingDecision, setSavingDecision] = useState(null);
  const [actionError, setActionError] = useState('');
  const [actionErrorReviewId, setActionErrorReviewId] = useState(null);
  const [notice, setNotice] = useState('');

  async function loadReviews() {
    setLoading(true);
    setLoadingError('');
    try {
      setReviews(await getAdminMeterReadingReviews());
    } catch (error) {
      setLoadingError(error.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadReviews();
  }, []);

  async function decide(review, decision) {
    const note = (reviewNotes[review.id] || '').trim();
    if (!note) {
      setActionErrorReviewId(review.id);
      setActionError('Add a review note before approving or rejecting.');
      return;
    }
    setSavingId(review.id);
    setSavingDecision(decision);
    setActionErrorReviewId(null);
    setActionError('');
    setNotice('');
    try {
      await decideAdminMeterReadingReview(review.id, decision, note);
      setNotice(
        decision === 'approve'
          ? 'Reading approved and the global total was updated.'
          : 'Reading rejected; the global total was not changed.'
      );
      await loadReviews();
    } catch (error) {
      setActionErrorReviewId(review.id);
      setActionError(error.message);
    } finally {
      setSavingId(null);
      setSavingDecision(null);
    }
  }

  return (
    <section className="admin-meter-review" aria-busy={loading}>
      <header className="admin-meter-review-header">
        <div>
          <p className="eyebrow">METER EXCEPTIONS</p>
          <h2>Readings to review</h2>
          <p>Flagged readings wait here and do not change the global total until approved.</p>
        </div>
        <div className="admin-meter-review-tools">
          <span className="admin-meter-review-count" aria-live="polite">
            {loading ? 'Loading queue' : `${reviews.length} awaiting review`}
          </span>
          <button
            className="outline-button"
            type="button"
            onClick={() => void loadReviews()}
            disabled={loading}
            aria-busy={loading}
          >
            {loading ? 'Refreshing...' : 'Refresh queue'}
          </button>
        </div>
      </header>
      {notice && <p className="notice" role="status">{notice}</p>}
      {loading ? (
        <div className="admin-meter-review-state" role="status">
          <span className="admin-meter-review-spinner" aria-hidden="true" />
          <p>Loading the review queue...</p>
        </div>
      ) : loadingError ? (
        <div className="admin-meter-review-state admin-meter-review-state--error">
          <p role="alert">{loadingError}</p>
          <button className="outline-button" type="button" onClick={() => void loadReviews()}>
            Try again
          </button>
        </div>
      ) : reviews.length === 0 ? (
        <div className="admin-meter-review-empty">
          <span className="admin-meter-review-empty-icon">
            <AppIcon name="check" size={20} />
          </span>
          <div>
            <h3>All caught up</h3>
            <p>No meter readings are waiting for administrator review.</p>
          </div>
        </div>
      ) : (
        <div className="admin-meter-review-list">
          {reviews.map((review) => {
            const totalChange =
              review.cumulativeTotalInteger != null &&
              review.previousGlobalTotalInteger != null
                ? review.cumulativeTotalInteger - review.previousGlobalTotalInteger
                : null;
            const topRowDifference =
              totalChange != null && review.topCurrentFillMilliLitres != null
                ? review.topCurrentFillMilliLitres - totalChange
                : null;
            const photoUrl = review.meterPhotoId
              ? apiUrl(`/api/meter-photos/${review.meterPhotoId}/content`)
              : null;

            return (
            <article className="admin-meter-review-card" key={review.id}>
              <header className="admin-meter-review-card-header">
                <div>
                  <p className="eyebrow">PENDING DECISION</p>
                  <h3>Reading #{review.id}</h3>
                  <p className="admin-meter-review-context">
                    Submitted {formatDate(review.submittedAt)}
                    <span aria-hidden="true">·</span>
                    Odometer {formatMileage(review.odometerMiles)} mi
                  </p>
                </div>
                <span className="admin-meter-review-source">
                  {(review.readingSource || 'unknown').toUpperCase()}
                </span>
              </header>
              <div className="admin-meter-review-card-content">
                <div className="admin-meter-review-reading">
                  <div className="admin-meter-review-metrics">
                    <div className="admin-meter-review-metric">
                      <span>Fill amount</span>
                      <strong>
                        {review.currentFillMilliLitres == null
                          ? 'Not provided'
                          : `${(review.currentFillMilliLitres / 1000).toFixed(3)} L`}
                      </strong>
                    </div>
                    <div className="admin-meter-review-metric">
                      <span>New global total</span>
                      <strong>
                        {review.cumulativeTotalInteger == null
                          ? 'Unreadable'
                          : `${formatMilliLitres(review.cumulativeTotalInteger)} L`}
                      </strong>
                    </div>
                    <div className="admin-meter-review-metric">
                      <span>Previous accepted</span>
                      <strong>
                        {review.previousGlobalTotalInteger == null
                          ? 'Not established'
                          : `${formatMilliLitres(review.previousGlobalTotalInteger)} L`}
                      </strong>
                    </div>
                    <div className="admin-meter-review-metric">
                      <span>Top-row evidence</span>
                      <strong>
                        {review.topCurrentFillMilliLitres == null
                          ? 'Missing'
                          : `${(review.topCurrentFillMilliLitres / 1000).toFixed(3)} L`}
                      </strong>
                    </div>
                  </div>
                  <div className="admin-meter-review-raw">
                    <div>
                      <span>Raw TOP digits</span>
                      <code>{review.currentFillRawDigits || 'Missing'}</code>
                    </div>
                    <div>
                      <span>Raw TOTAL digits</span>
                      <code>{review.cumulativeTotalRawDigits || 'Missing'}</code>
                    </div>
                  </div>
                  {totalChange != null && (
                    <div className="admin-meter-review-comparison">
                      <span>Change since previous accepted total</span>
                      <strong>{formatMilliLitres(totalChange)} L</strong>
                      {topRowDifference != null && (
                        <small>
                          {topRowDifference === 0
                            ? 'Matches the top-row reading exactly.'
                            : `Top-row difference: ${formatMilliLitres(topRowDifference)} L.`}
                        </small>
                      )}
                    </div>
                  )}
                  {review.fillCalculation === 'global_total_difference' && (
                    <p className="admin-meter-review-calculated">
                      Fill calculated from the global-total difference
                    </p>
                  )}
                  <div className="admin-meter-review-warnings">
                    <strong>
                      {review.warnings?.length
                        ? `${review.warnings.length} reason${review.warnings.length === 1 ? '' : 's'} flagged`
                        : 'Flagged for administrator review'}
                    </strong>
                    {review.warnings?.length > 0 ? (
                      <ul>
                        {review.warnings.map((warning) => (
                          <li key={warning}>{warning}</li>
                        ))}
                      </ul>
                    ) : (
                      <p>Check the evidence and readings before deciding.</p>
                    )}
                  </div>
                </div>
                <div className="admin-meter-review-decision">
                  {photoUrl ? (
                    <figure className="admin-meter-review-evidence">
                      <a
                        className="admin-meter-review-evidence-link"
                        href={photoUrl}
                        target="_blank"
                        rel="noreferrer"
                        aria-label={`Open full-size meter photo for reading ${review.id}`}
                      >
                        <img
                          src={photoUrl}
                          alt={`Original meter photo for reading ${review.id}`}
                          loading="lazy"
                        />
                      </a>
                      <figcaption>
                        Original meter photo
                        <a
                          href={photoUrl}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open full size
                        </a>
                      </figcaption>
                    </figure>
                  ) : (
                    <div className="admin-meter-review-no-evidence">
                      No photo was attached to this reading.
                    </div>
                  )}
                  <label className="admin-meter-review-note">
                    <span>Review note <em>Required</em></span>
                    <textarea
                      rows="3"
                      maxLength="500"
                      required
                      value={reviewNotes[review.id] || ''}
                      onChange={(event) =>
                        {
                          setReviewNotes((current) => ({
                            ...current,
                            [review.id]: event.target.value
                          }));
                          if (actionErrorReviewId === review.id) {
                            setActionError('');
                            setActionErrorReviewId(null);
                          }
                        }
                      }
                      placeholder="Explain what you checked and why you are approving or rejecting."
                    />
                    <small>A note is saved with either decision for the audit trail.</small>
                  </label>
                  <div className="admin-meter-review-actions">
                    <button
                      className="primary-button"
                      type="button"
                      disabled={savingId === review.id}
                      aria-busy={savingId === review.id && savingDecision === 'approve'}
                      onClick={() => void decide(review, 'approve')}
                    >
                      {savingId === review.id && savingDecision === 'approve'
                        ? 'Approving...'
                        : 'Approve reading'}
                    </button>
                    <button
                      className="outline-button"
                      type="button"
                      disabled={savingId === review.id}
                      aria-busy={savingId === review.id && savingDecision === 'reject'}
                      onClick={() => void decide(review, 'reject')}
                    >
                      {savingId === review.id && savingDecision === 'reject'
                        ? 'Rejecting...'
                        : 'Reject'}
                    </button>
                  </div>
                  {actionErrorReviewId === review.id && actionError && (
                    <p className="admin-meter-review-action-error" role="alert">
                      {actionError}
                    </p>
                  )}
                </div>
              </div>
            </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function AdminWorkspaceTabs({
  activeTab,
  globalMeter,
  globalMeterHistory,
  loading,
  onChangeTab,
  onGlobalMeterEventCreated,
  onDownload,
  onEmail,
  onExport,
  onNotify
}) {
  if (activeTab === 'adminNct') {
    return <NctMonitoring />;
  }
  if (activeTab === 'adminEmployees') {
    return (
      <AdminEmployeeRecordsTab
        onDownload={onDownload}
        onEmail={onEmail}
        onExport={onExport}
      />
    );
  }
  if (activeTab === 'adminSummary') {
    return (
      <AdminSummaryTab
        globalMeter={globalMeter}
        globalMeterHistory={globalMeterHistory}
        loading={loading}
        onOpenNct={() => onChangeTab('adminNct')}
        onOpenEmployeeRecords={() => onChangeTab('adminEmployees')}
        onGlobalMeterEventCreated={onGlobalMeterEventCreated}
      />
    );
  }
  if (activeTab === 'adminRegistry') {
    return <AdminPanel onNotify={onNotify} />;
  }
  if (activeTab === 'adminMeterReviews') {
    return <AdminMeterReadingReviews />;
  }
  return (
    <AdminSummaryTab
      globalMeter={globalMeter}
      globalMeterHistory={globalMeterHistory}
      loading={loading}
      onOpenNct={() => onChangeTab('adminNct')}
      onOpenEmployeeRecords={() => onChangeTab('adminEmployees')}
      onGlobalMeterEventCreated={onGlobalMeterEventCreated}
    />
  );
}

function Workspace({
  employee,
  vehicle,
  vehicleRecords,
  globalMeter,
  globalMeterHistory,
  theme,
  records,
  loading,
  onLogout,
  onDownload,
  onEmail,
  onExport,
  onNotify,
  onRecordCreated,
  onGlobalMeterEventCreated,
  onToggleTheme
}) {
  const isAdmin = employee.role === 'admin';
  const isBoss = employee.role === 'boss';
  const isManagement = ['admin', 'boss'].includes(employee.role);
  const [activeSection, setActiveSection] = useState(() =>
    isAdmin ? 'adminSummary' : 'overview'
  );
  const showFullHistory = isAdmin;
  const showFlaggedReadings = ['admin', 'boss'].includes(employee.role);
  const showCumulativeTotal = ['admin', 'boss'].includes(employee.role);
  const renderAssignedFuelEntry = isBoss
    ? (onSaved) => (
        <section className="entry-section boss-fuel-entry-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">FLEET VEHICLE</p>
              <h3>Record a fill</h3>
              <p>Use your assigned vehicle or find another by registration number.</p>
            </div>
            <span className="read-only-badge">Verified readings required</span>
          </div>
          <div className="entry-layout">
            <FuelForm
              vehicle={vehicle}
              onRecordCreated={onSaved}
              allowVehicleSelection
            />
            <WorkflowGuide />
          </div>
        </section>
      )
    : undefined;

  if (isBoss || (isAdmin && activeSection === 'adminExecutive')) {
    return (
      <BossDashboard
        employee={employee}
        theme={theme}
        onLogout={onLogout}
        onNotify={onNotify}
        onToggleTheme={onToggleTheme}
        onFuelRecordCreated={isBoss ? onRecordCreated : undefined}
        renderFuelEntry={renderAssignedFuelEntry}
        onBackToWorkspace={
          isAdmin ? () => setActiveSection('adminSummary') : undefined
        }
      />
    );
  }

  return (
    <main className={`app-shell${isAdmin ? ' admin-app-shell' : ' employee-app-shell'}`}>
      <aside className="sidebar">
        <Brand />
        <div className="sidebar-label">WORKSPACE</div>
        <nav>
          {isAdmin ? (
            <div className="admin-sidebar-tabs" role="tablist" aria-label="Admin dashboard">
              <button
                className={activeSection === 'adminEmployees' ? 'active' : ''}
                type="button"
                role="tab"
                aria-selected={activeSection === 'adminEmployees'}
                onClick={() => setActiveSection('adminEmployees')}
              >
                <AppIcon name="team" />
                Employees
              </button>
              <button
                className={activeSection === 'adminSummary' ? 'active' : ''}
                type="button"
                role="tab"
                aria-selected={activeSection === 'adminSummary'}
                onClick={() => setActiveSection('adminSummary')}
              >
                <AppIcon name="overview" />
                Summary
              </button>
              <button
                className={activeSection === 'adminRegistry' ? 'active' : ''}
                type="button"
                role="tab"
                aria-selected={activeSection === 'adminRegistry'}
                onClick={() => setActiveSection('adminRegistry')}
              >
                <AppIcon name="registry" />
                Registry
              </button>
              <button
                className={activeSection === 'adminMeterReviews' ? 'active' : ''}
                type="button"
                role="tab"
                aria-selected={activeSection === 'adminMeterReviews'}
                onClick={() => setActiveSection('adminMeterReviews')}
              >
                <AppIcon name="review" />
                Meter review
              </button>
              <button
                className={activeSection === 'adminNct' ? 'active' : ''}
                type="button"
                role="tab"
                aria-selected={activeSection === 'adminNct'}
                onClick={() => setActiveSection('adminNct')}
              >
                <AppIcon name="review" />
                NCT expiry
              </button>
            </div>
          ) : (
            <>
            <a
              className={activeSection === 'overview' ? 'active' : ''}
              href="#overview"
              aria-current={activeSection === 'overview' ? 'location' : undefined}
              onClick={() => setActiveSection('overview')}
            >
              <AppIcon name="overview" />
              Overview
            </a>
            {isBoss && (
              <a
                className={activeSection === 'bossSummary' ? 'active' : ''}
                href="#bossSummary"
                aria-current={activeSection === 'bossSummary' ? 'location' : undefined}
                onClick={() => setActiveSection('bossSummary')}
              >
                <AppIcon name="overview" />
                Summary
              </a>
            )}
            <a
              className={activeSection === 'newFill' ? 'active' : ''}
              href="#newFill"
              aria-current={activeSection === 'newFill' ? 'location' : undefined}
              onClick={() => setActiveSection('newFill')}
            >
              <AppIcon name="fuel" />
              New fill
            </a>
            {showCumulativeTotal && (
              <a
                className={activeSection === 'globalMeter' ? 'active' : ''}
                href="#globalMeter"
                aria-current={activeSection === 'globalMeter' ? 'location' : undefined}
                onClick={() => setActiveSection('globalMeter')}
              >
                <AppIcon name="meter" />
                Global meter
              </a>
            )}
            {showFullHistory && (
              <a
                className={activeSection === 'history' ? 'active' : ''}
                href="#history"
                aria-current={activeSection === 'history' ? 'location' : undefined}
                onClick={() => setActiveSection('history')}
              >
                <AppIcon name="history" />
                History
              </a>
            )}
            {showFullHistory && (
            <a
              className={activeSection === 'vehicleHistory' ? 'active' : ''}
              href="#vehicleHistory"
              aria-current={activeSection === 'vehicleHistory' ? 'location' : undefined}
              onClick={() => setActiveSection('vehicleHistory')}
            >
              <AppIcon name="vehicle" />
              Vehicle history
            </a>
            )}
            {isBoss ? (
              <a
                className={activeSection === 'bossSummary' ? 'active' : ''}
                href="#bossNct"
                aria-current={activeSection === 'bossSummary' ? 'location' : undefined}
                onClick={() => setActiveSection('bossSummary')}
              >
                <AppIcon name="review" />
                NCT expiry
              </a>
            ) : !isAdmin && isManagement ? (
              <a
                className={activeSection === 'nctAlerts' ? 'active' : ''}
                href="#nctAlerts"
                aria-current={activeSection === 'nctAlerts' ? 'location' : undefined}
                onClick={() => setActiveSection('nctAlerts')}
              >
                <AppIcon name="review" />
                NCT expiry
              </a>
            ) : null}
            </>
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="status-dot" />
          <div>
            <strong>Meter review enabled</strong>
            <small>Verify before saving</small>
          </div>
        </div>
      </aside>

      <section
        className={`content${isAdmin && activeSection === 'adminEmployees' ? ' content-admin-employees' : ''}`}
      >
        <header className="topbar">
          <div>
            <p className="eyebrow">MONITOR / FUEL LOG</p>
            <h2>Welcome back, {employee.name}.</h2>
          </div>
          <div
            className={`topbar-actions${!isAdmin ? ' employee-topbar-actions' : ''}`}
          >
            {!isAdmin && (
              <a
                className="topbar-primary-action"
                href="#newFill"
                onClick={() => setActiveSection('newFill')}
              >
                <AppIcon name="fuel" size={15} />
                <span>Record a fill</span>
              </a>
            )}
            <div className="topbar-utility-actions">
              <ThemeToggle theme={theme} onToggle={onToggleTheme} />
              <button className="text-button" type="button" onClick={onLogout}>
                Sign out <span>-&gt;</span>
              </button>
            </div>
          </div>
        </header>

        {isAdmin ? (
          <AdminWorkspaceTabs
            activeTab={activeSection}
            globalMeter={globalMeter}
            globalMeterHistory={globalMeterHistory}
            loading={loading}
            onChangeTab={setActiveSection}
            onGlobalMeterEventCreated={onGlobalMeterEventCreated}
            onDownload={onDownload}
            onEmail={onEmail}
            onExport={onExport}
            onNotify={onNotify}
          />
        ) : activeSection === 'nctAlerts' && isManagement ? (
          <NctMonitoring />
        ) : (
          <>
            <div className="summary-grid">
              <DashboardSection
                records={records}
                vehicle={vehicle}
                loading={loading}
                showFullHistory={showFullHistory}
                showFlaggedReadings={showFlaggedReadings}
                showCumulativeTotal={showCumulativeTotal}
                showRecentExpanded={!isAdmin}
              />
            </div>

            {showCumulativeTotal && (
              <GlobalMeterDashboard
                summary={globalMeter}
                history={globalMeterHistory}
                loading={loading}
                onRecordEvent={onGlobalMeterEventCreated}
                onOpenNct={() => {
                  if (isBoss) {
                    setActiveSection('bossSummary');
                    document.getElementById('bossNct')?.scrollIntoView({
                      behavior: 'smooth'
                    });
                    return;
                  }
                  setActiveSection('nctAlerts');
                }}
                showNctAlerts={false}
              />
            )}

            <div className="dashboard-grid dashboard-grid-single">
              <section id="newFill" className="entry-section">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">NEW ENTRY</p>
                    <h3>Record a fill</h3>
                  </div>
                  <span className="read-only-badge">Verified readings required</span>
                </div>
                <div className="entry-layout">
                  <FuelForm vehicle={vehicle} onRecordCreated={onRecordCreated} />
                  <WorkflowGuide />
                </div>
              </section>
            </div>
            {showFullHistory && (
            <HistorySection
              records={records}
              loading={loading}
              onDownload={onDownload}
              onEmail={onEmail}
              onExport={onExport}
            />
            )}
            {showFullHistory && (
          <HistorySection
            id="vehicleHistory"
            eyebrow="ASSIGNED VEHICLE"
            title="Vehicle fuel history"
            records={vehicleRecords}
            loading={loading}
            onDownload={onDownload}
            onEmail={onEmail}
            onExport={onExport}
          />
            )}
          </>
        )}
        <footer>
          <span>Brusna / Fleet fuel control</span>
          <span>
            {records.length} record{records.length === 1 ? '' : 's'}
          </span>
        </footer>
      </section>
    </main>
  );
}

export default function App() {
  const [theme, setTheme] = useState(getPreferredTheme);
  const [employee, setEmployee] = useState(null);
  const [pendingEmployee, setPendingEmployee] = useState(null);
  const [isRestoringSession, setIsRestoringSession] = useState(true);
  const [vehicle, setVehicle] = useState(null);
  const [records, setRecords] = useState([]);
  const [vehicleRecords, setVehicleRecords] = useState([]);
  const [globalMeter, setGlobalMeter] = useState(null);
  const [globalMeterHistory, setGlobalMeterHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [toast, setToast] = useState('');

  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', theme === 'dark' ? '#111815' : '#f4f6f2');
    window.localStorage.setItem('diesel-desk-theme', theme);
  }, [theme]);

  async function loadWorkspaceData(employeeContext = employee) {
    setLoading(true);
    const isManagement = ['admin', 'boss'].includes(employeeContext?.role);
    const requests = [
      getFuelRecords(),
      getAssignedVehicle(),
      getVehicleFuelRecords()
    ];
    if (isManagement) {
      requests.push(getGlobalMeterSummary(), getGlobalMeterHistory());
    }
    const results = await Promise.allSettled(requests);
    if (results[0].status === 'fulfilled') {
      setRecords(results[0].value);
    }
    if (results[1].status === 'fulfilled') {
      setVehicle(results[1].value);
    }
    if (results[2].status === 'fulfilled') {
      setVehicleRecords(results[2].value);
    }
    if (isManagement) {
      if (results[3].status === 'fulfilled') {
        setGlobalMeter(results[3].value);
      }
      if (results[4].status === 'fulfilled') {
        setGlobalMeterHistory(results[4].value);
      }
    } else {
      setGlobalMeter(null);
      setGlobalMeterHistory([]);
    }
    const failure = results.find((result) => result.status === 'rejected');
    if (failure?.status === 'rejected') {
      setToast(`Could not load workspace data: ${failure.reason.message}`);
    }
    setLoading(false);
  }

  useEffect(() => {
    let active = true;
    async function restoreSession() {
      try {
        const currentEmployee = await getCurrentEmployee();
        if (!active) return;
        setEmployee(currentEmployee);
        setIsRestoringSession(false);
        await loadWorkspaceData(currentEmployee);
      } catch (error) {
        if (active) {
          if (error.status !== 401) {
            setToast(`Could not restore session: ${error.message}`);
          }
          setIsRestoringSession(false);
        }
      }
    }
    restoreSession();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!toast) return undefined;
    const timeoutId = window.setTimeout(() => setToast(''), 3300);
    return () => window.clearTimeout(timeoutId);
  }, [toast]);

  async function handleLogin(event) {
    event.preventDefault();
    setLoading(true);
    setLoginError('');
    const data = new FormData(event.currentTarget);
    try {
      const currentEmployee = await login(
        data.get('username'),
        data.get('password')
      );
      setPendingEmployee(currentEmployee);
    } catch (error) {
      setLoginError(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function completeLoginTransition() {
    if (!pendingEmployee) return;
    const currentEmployee = pendingEmployee;
    setPendingEmployee(null);
    setEmployee(currentEmployee);
    try {
      await loadWorkspaceData(currentEmployee);
    } catch (error) {
      setToast(`Could not load workspace data: ${error.message}`);
    }
  }

  async function handleLogout() {
    try {
      await logout();
    } catch (error) {
      setToast(`Could not sign out cleanly: ${error.message}`);
    } finally {
      setEmployee(null);
      setVehicle(null);
      setRecords([]);
      setVehicleRecords([]);
      setGlobalMeter(null);
      setGlobalMeterHistory([]);
    }
  }

  async function handleRecordCreated(record) {
    await loadWorkspaceData(employee);
    if (record.status === 'review_pending') {
      setToast(
        'Reading submitted for administrator review. It has not been saved as a fuel transaction yet.'
      );
      return;
    }
    setToast(
      record.record?.meterWarnings?.length
        ? 'Fuel record saved to the dashboard with meter warnings.'
        : 'Fuel record saved to the dashboard.'
    );
  }

  async function handleGlobalMeterEventCreated(eventData) {
    await createGlobalMeterEvent(eventData);
    await loadWorkspaceData(employee);
    setToast(
      eventData.eventType === 'baseline'
        ? 'Initial global meter baseline set.'
        : 'Global meter reset/replacement recorded.'
    );
  }

  function exportAll(recordsToExport = records) {
    if (!recordsToExport.length) {
      setToast('There are no records to export yet.');
      return;
    }
    downloadJson(
      recordsToExport.map(recordWithMiles),
      `diesel-desk-records-${new Date().toISOString().slice(0, 10)}.json`
    );
    setToast('All records exported.');
  }

  return (
    <>
      {isRestoringSession ? (
        <SessionRestoreScreen />
      ) : employee ? (
          <Workspace
            employee={employee}
            vehicle={vehicle}
            vehicleRecords={vehicleRecords}
            globalMeter={globalMeter}
            globalMeterHistory={globalMeterHistory}
            theme={theme}
            records={records}
            loading={loading}
            onLogout={handleLogout}
            onDownload={downloadReport}
            onEmail={emailReport}
            onExport={exportAll}
            onNotify={setToast}
            onRecordCreated={handleRecordCreated}
            onGlobalMeterEventCreated={handleGlobalMeterEventCreated}
            onToggleTheme={() =>
              setTheme((currentTheme) => (currentTheme === 'dark' ? 'light' : 'dark'))
            }
          />
      ) : (
        <LoginScreen
          error={loginError}
          loading={loading}
          success={Boolean(pendingEmployee)}
          onLogin={handleLogin}
          onSuccessAnimationEnd={completeLoginTransition}
          theme={theme}
          onToggleTheme={() =>
            setTheme((currentTheme) => (currentTheme === 'dark' ? 'light' : 'dark'))
          }
        />
      )}
      <div className={`toast${toast ? ' show' : ''}`} role="status">
        {toast}
      </div>
    </>
  );
}

function getPreferredTheme() {
  const savedTheme = window.localStorage.getItem('diesel-desk-theme');
  if (savedTheme === 'light' || savedTheme === 'dark') return savedTheme;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
