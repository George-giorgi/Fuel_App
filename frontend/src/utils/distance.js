export function formatMileage(miles) {
  return miles.toLocaleString('en-IE', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1
  });
}
