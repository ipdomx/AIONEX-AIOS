'use strict';
// Disposable loopback/in-memory checks; no Firebase, provider or production IO.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {createRequire} = require('node:module');
const localRequire = createRequire(path.resolve(__dirname, '../../vip-frontend/package.json'));
const grpc = localRequire('@grpc/grpc-js');

test('patched gRPC supports an ordinary local unary exchange', {timeout: 7000}, async () => {
  assert.equal(localRequire('@grpc/grpc-js/package.json').version, '1.13.6');
  const serialize = value => Buffer.from(JSON.stringify(value));
  const deserialize = value => JSON.parse(value.toString());
  const definition = {
    ping: {path: '/isolated.SecurityRefresh/Ping', requestStream: false, responseStream: false,
      requestSerialize: serialize, requestDeserialize: deserialize,
      responseSerialize: serialize, responseDeserialize: deserialize}
  };
  const server = new grpc.Server();
  let client;
  try {
    server.addService(definition, {ping(call, callback) {callback(null, {message: call.request.message});}});
    const port = await new Promise((resolve, reject) => server.bindAsync('127.0.0.1:0', grpc.ServerCredentials.createInsecure(),
      (error, boundPort) => error ? reject(error) : resolve(boundPort)));
    const Client = grpc.makeGenericClientConstructor(definition, 'SecurityRefresh');
    client = new Client(`127.0.0.1:${port}`, grpc.credentials.createInsecure());
    const answer = await new Promise((resolve, reject) => client.ping({message: 'isolated-check'},
      {deadline: new Date(Date.now() + 3000)}, (error, value) => error ? reject(error) : resolve(value)));
    assert.deepEqual(answer, {message: 'isolated-check'});
  } finally {
    if (client) client.close();
    server.forceShutdown();
  }
});

test('patched root brace expansion preserves normal expansion and bounds nesting', {timeout: 5000}, () => {
  assert.equal(localRequire('brace-expansion/package.json').version, '1.1.21');
  const expand = localRequire('brace-expansion');
  assert.deepEqual(expand('file-{a,b}'), ['file-a', 'file-b']);
  assert.doesNotThrow(() => expand('{'.repeat(3200) + 'a,b' + '}'.repeat(3200)));
});

test('patched nested brace expansion retains bounded nesting', {timeout: 5000}, async () => {
  const location = path.resolve(__dirname, '../../vip-frontend/node_modules/@typescript-eslint/typescript-estree/node_modules/brace-expansion');
  assert.equal(require(path.join(location, 'package.json')).version, '5.0.12');
  const module = await import(require('node:url').pathToFileURL(require.resolve(location)).href);
  const expand = module.expand ?? module.default;
  assert.equal(typeof expand, 'function');
  assert.deepEqual(expand('file-{a,b}'), ['file-a', 'file-b']);
  assert.doesNotThrow(() => expand('{'.repeat(3200) + 'a,b' + '}'.repeat(3200)));
});
