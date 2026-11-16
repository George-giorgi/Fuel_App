import assert from 'node:assert/strict';
import test from 'node:test';
import { formatMileage } from '../src/utils/distance.js';

test('formats stored mileage directly in miles to one decimal place', () => {
  assert.equal(formatMileage(0), '0.0');
  assert.equal(formatMileage(12345.6), '12,345.6');
});
