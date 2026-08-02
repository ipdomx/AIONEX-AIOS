/*
 * Some restricted build containers do not mount /proc. In that environment,
 * Node throws from process.memoryUsage() before Next.js can compile. Keep the
 * native implementation everywhere else and provide a build-only fallback.
 */
try {
  process.memoryUsage();
} catch {
  const safeMemoryUsage = () => ({
    rss: 0,
    heapTotal: 0,
    heapUsed: 0,
    external: 0,
    arrayBuffers: 0
  });
  safeMemoryUsage.rss = () => 0;
  process.memoryUsage = safeMemoryUsage;
}

try {
  require("node:os").networkInterfaces();
} catch {
  require("node:os").networkInterfaces = () => ({
    loopback: [
      {
        address: "127.0.0.1",
        netmask: "255.0.0.0",
        family: "IPv4",
        mac: "00:00:00:00:00:00",
        internal: true,
        cidr: "127.0.0.1/8"
      }
    ]
  });
}
