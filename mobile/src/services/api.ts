import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { API_BASE_URL } from '../config';
import type {
  AuthResponse, User, Room, RoomSchedule, HistoryBooking, TimeSlots, CheckAvailabilityResult,
} from '../types';

const client = axios.create({ baseURL: API_BASE_URL, timeout: 10000 });

client.interceptors.request.use(async (config) => {
  const token = await AsyncStorage.getItem('auth_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

client.interceptors.response.use(
  (res) => res,
  (err) => {
    const msg = err.response?.data?.detail || err.message || 'Network error';
    return Promise.reject(new Error(msg));
  },
);

export const api = {
  // Auth
  login: (employee_code: string, password: string): Promise<AuthResponse> =>
    client.post('/api/v1/auth/login', { employee_code, password }).then((r) => r.data),

  me: (): Promise<User> =>
    client.get('/api/v1/auth/me').then((r) => r.data),

  changePassword: (old_password: string, new_password: string): Promise<{ message: string }> =>
    client.put('/api/v1/auth/change-password', { old_password, new_password }).then((r) => r.data),

  // Rooms
  getRooms: (): Promise<Room[]> =>
    client.get('/api/v1/rooms').then((r) => r.data),

  getTimeSlots: (): Promise<TimeSlots> =>
    client.get('/api/v1/time-slots').then((r) => r.data),

  // Schedule
  getTodaySchedule: (): Promise<RoomSchedule[]> =>
    client.get('/api/v1/schedule/today').then((r) => r.data),

  // Bookings
  createBooking: (data: {
    room_id: number;
    date: string;
    start_time: string;
    end_time: string;
    purpose?: string;
  }) => client.post('/api/v1/bookings', data).then((r) => r.data),

  cancelBooking: (id: number): Promise<{ message: string }> =>
    client.delete(`/api/v1/bookings/${id}`).then((r) => r.data),

  searchBookings: (params: {
    name?: string;
    room_id?: number;
    date_from?: string;
    date_to?: string;
  }): Promise<HistoryBooking[]> =>
    client.get('/api/v1/bookings/search', { params }).then((r) => r.data),

  // Dry-run check — does NOT create a booking
  checkAvailability: (data: {
    room_id: number;
    date: string;
    start_time: string;
    end_time: string;
  }): Promise<CheckAvailabilityResult> =>
    client.post('/api/v1/bookings/check', data).then((r) => r.data),

  // Admin override
  setRoomOverride: (room_id: number, reason: string): Promise<{ message: string }> =>
    client.post(`/api/v1/admin/rooms/${room_id}/override`, { reason }).then((r) => r.data),

  clearRoomOverride: (room_id: number): Promise<{ message: string }> =>
    client.delete(`/api/v1/admin/rooms/${room_id}/override`).then((r) => r.data),
};
