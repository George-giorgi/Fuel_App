export async function onRequest({ request, env }) {
  if (!env.API_ORIGIN) {
    return new Response('API_ORIGIN is not configured.', { status: 500 });
  }

  const apiOrigin = new URL(env.API_ORIGIN);
  if (
    apiOrigin.protocol !== 'https:' ||
    apiOrigin.pathname !== '/' ||
    apiOrigin.search ||
    apiOrigin.hash
  ) {
    return new Response('API_ORIGIN must be an HTTPS origin.', { status: 500 });
  }

  const upstreamUrl = new URL(request.url);
  upstreamUrl.protocol = apiOrigin.protocol;
  upstreamUrl.hostname = apiOrigin.hostname;
  upstreamUrl.port = apiOrigin.port;

  const headers = new Headers(request.headers);
  headers.delete('host');
  const clientIp = request.headers.get('CF-Connecting-IP');
  if (clientIp) headers.set('X-Forwarded-For', clientIp);
  const body =
    request.method === 'GET' || request.method === 'HEAD'
      ? undefined
      : request.body;

  return fetch(
    new Request(upstreamUrl, {
      method: request.method,
      headers,
      body,
      duplex: body ? 'half' : undefined,
      redirect: 'manual'
    })
  );
}
