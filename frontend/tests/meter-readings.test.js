import assert from 'node:assert/strict';
import test from 'node:test';
import { ocrValueToRawDigits } from '../src/utils/meterReadings.js';

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
