export interface User {
  id: number;
  employee_code: string;
  name: string;
  branch: string;
  department: string;
  designation: string;
  must_change_password: boolean;
  is_admin: boolean;
}

export interface AuthResponse {
  token: string;
  user: User;
}

export type RoomStatus = 'available' | 'occupied' | 'booked';

export interface RoomBooking {
  id: number;
  start_time: string;
  end_time: string;
  booked_by: string;
  purpose: string;
}

export interface Room {
  id: number;
  name: string;
  floor: number;
  size: string;
  amenities: string[];
  status: RoomStatus;
  booking: RoomBooking | null;
  has_override: boolean;
  override_reason: string | null;
}

export interface CheckAvailabilityResult {
  available: boolean;
  conflicts: { start_time: string; end_time: string; booked_by: string; purpose: string }[];
}

export interface ScheduleBooking {
  id: number;
  start_time: string;
  end_time: string;
  booked_by: string;
  purpose: string;
  is_now: boolean;
  can_cancel: boolean;
}

export interface RoomSchedule {
  room_id: number;
  room_name: string;
  floor: number;
  bookings: ScheduleBooking[];
}

export interface HistoryBooking {
  id: number;
  room_id: number;
  room_name: string;
  date: string;
  start_time: string;
  end_time: string;
  booked_by: string;
  purpose: string;
  can_cancel: boolean;
}

export interface TimeSlots {
  slots: string[];
}
