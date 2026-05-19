// Set EXPO_PUBLIC_API_URL in mobile/.env for your environment.
// Examples:
//   Android emulator : http://10.0.2.2:8000
//   iOS simulator    : http://localhost:8000
//   Physical device  : http://<your-machine-LAN-ip>:8000
//   Production       : https://api.yourdomain.com
declare const process: { env: Record<string, string | undefined> };

export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL ?? 'http://192.168.10.215:8000';
