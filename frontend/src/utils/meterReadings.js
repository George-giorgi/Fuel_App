export function ocrValueToRawDigits(value) {
  if (value == null) return '';

  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return '';
  if (Number.isSafeInteger(number)) return String(number);

  const milliLitres = number * 1000;
  return Number.isSafeInteger(milliLitres) ? String(milliLitres) : '';
}
