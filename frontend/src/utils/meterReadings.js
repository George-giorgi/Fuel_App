export function ocrValueToRawDigits(value) {
  if (value == null) return '';

  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return '';
  if (Number.isSafeInteger(number)) return String(number);

  const milliLitres = number * 1000;
  return Number.isSafeInteger(milliLitres) ? String(milliLitres) : '';
}

export function formatRawMeterDigitsAsLitres(rawDigits) {
  if (typeof rawDigits !== 'string' || !/^[0-9]+$/.test(rawDigits)) {
    return null;
  }

  const paddedDigits = rawDigits.padStart(4, '0');
  const wholeLitres = paddedDigits
    .slice(0, -3)
    .replace(/^0+(?=\d)/, '')
    .replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const milliLitres = paddedDigits.slice(-3);
  return `${wholeLitres}.${milliLitres}`;
}
