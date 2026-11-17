import assert from 'node:assert/strict';
import test from 'node:test';
import {
  formatOcrCurrentFill,
  formatRawMeterDigitsAsLitres,
  ocrValueToRawDigits
} from '../src/utils/meterReadings.js';

test('converts decimal litre OCR values to raw milli-litre digits', () => {
  assert.equal(ocrValueToRawDigits(261.563), '261563');
});

test('preserves integer OCR values that already contain raw digits', () => {
  assert.equal(ocrValueToRawDigits(261563), '261563');
});

test('does not invent digits for missing, invalid, or over-precision values', () => {
  assert.equal(ocrValueToRawDigits(null), '');
  assert.equal(ocrValueToRawDigits(Number.NaN), '');
  assert.equal(ocrValueToRawDigits(-1), '');
  assert.equal(ocrValueToRawDigits(1.2345), '');
});

test('formats raw fill and total digits as thousandths of a litre', () => {
  assert.equal(formatRawMeterDigitsAsLitres('20000'), '20.000');
  assert.equal(formatRawMeterDigitsAsLitres('120000'), '120.000');
  assert.equal(formatRawMeterDigitsAsLitres('50'), '0.050');
  assert.equal(formatRawMeterDigitsAsLitres('001000000'), '1,000.000');
});

test('does not format invalid raw meter digits', () => {
  assert.equal(formatRawMeterDigitsAsLitres(''), null);
  assert.equal(formatRawMeterDigitsAsLitres('20.000'), null);
  assert.equal(formatRawMeterDigitsAsLitres('20,000'), null);
});

test('formats OCR current fill integers as raw milli-litres', () => {
  assert.equal(formatOcrCurrentFill(null, 20000), '20.000');
  assert.equal(formatOcrCurrentFill('20000', 20000), '20.000');
  assert.equal(formatOcrCurrentFill(null, 20.125), '20.125');
  assert.equal(formatOcrCurrentFill(null, null), 'Not recorded');
});
