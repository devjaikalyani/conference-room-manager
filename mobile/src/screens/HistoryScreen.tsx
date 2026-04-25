import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TextInput,
  TouchableOpacity, ActivityIndicator, Alert, Platform, Modal, FlatList,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import DateTimePicker from '@react-native-community/datetimepicker';
import { api } from '../services/api';
import { useAuth } from '../context/AuthContext';
import type { HistoryBooking } from '../types';

const ROOM_FILTERS = [
  { label: 'All Rooms', value: 0 },
  { label: 'Floor 5 – Large', value: 5 },
  { label: 'Floor 4 – Large', value: 4 },
  { label: 'Floor 3 – Small', value: 3 },
  { label: 'Floor 2 – Small', value: 2 },
];

export default function HistoryScreen() {
  const { user } = useAuth();
  const [searchName, setSearchName]   = useState('');
  const [roomFilter, setRoomFilter]   = useState(ROOM_FILTERS[0]);
  const [dateFrom, setDateFrom]       = useState<Date | null>(null);
  const [dateTo, setDateTo]           = useState<Date | null>(null);
  const [showFrom, setShowFrom]       = useState(false);
  const [showTo, setShowTo]           = useState(false);
  const [roomModal, setRoomModal]     = useState(false);
  const [results, setResults]         = useState<HistoryBooking[]>([]);
  const [loading, setLoading]         = useState(false);
  const [searched, setSearched]       = useState(false);

  const handleSearch = async () => {
    setLoading(true);
    try {
      const data = await api.searchBookings({
        name: searchName.trim() || undefined,
        room_id: roomFilter.value || undefined,
        date_from: dateFrom ? dateFrom.toISOString().split('T')[0] : undefined,
        date_to: dateTo ? dateTo.toISOString().split('T')[0] : undefined,
      });
      setResults(data);
      setSearched(true);
    } catch (e: any) {
      Alert.alert('Error', e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = (id: number, bookedBy: string) => {
    if (!user?.is_admin && bookedBy.toLowerCase() !== user?.name.toLowerCase()) {
      return Alert.alert('Not Allowed', 'You can only cancel your own bookings.');
    }
    Alert.alert('Cancel Booking', 'Cancel this booking?', [
      { text: 'No', style: 'cancel' },
      {
        text: 'Cancel Booking', style: 'destructive',
        onPress: async () => {
          try {
            await api.cancelBooking(id);
            setResults((prev) => prev.filter((b) => b.id !== id));
          } catch (e: any) {
            Alert.alert('Error', e.message);
          }
        },
      },
    ]);
  };

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <ScrollView style={s.root} contentContainerStyle={s.content} showsVerticalScrollIndicator={false}>
        <Text style={s.title}>Booking History</Text>
        <Text style={s.sub}>Search and manage past bookings.</Text>

        {/* Search by name */}
        <Text style={s.label}>Search by Name</Text>
        <View style={s.inputRow}>
          <Ionicons name="search-outline" size={16} color="#8fa8c8" style={s.inputIcon} />
          <TextInput
            style={s.input}
            placeholder="Enter name..."
            placeholderTextColor="#3a5070"
            value={searchName}
            onChangeText={setSearchName}
          />
        </View>

        {/* Room filter */}
        <Text style={s.label}>Filter by Room</Text>
        <TouchableOpacity style={s.selector} onPress={() => setRoomModal(true)}>
          <Text style={s.selectorText}>{roomFilter.label}</Text>
          <Ionicons name="chevron-down" size={16} color="#8fa8c8" />
        </TouchableOpacity>

        {/* Date range */}
        <View style={s.dateRow}>
          <View style={s.dateCol}>
            <Text style={s.label}>From Date</Text>
            <TouchableOpacity style={s.selector} onPress={() => setShowFrom(true)}>
              <Text style={s.selectorText}>
                {dateFrom ? dateFrom.toISOString().split('T')[0] : 'Any'}
              </Text>
              <Ionicons name="calendar-outline" size={16} color="#8fa8c8" />
            </TouchableOpacity>
          </View>
          <View style={s.dateCol}>
            <Text style={s.label}>To Date</Text>
            <TouchableOpacity style={s.selector} onPress={() => setShowTo(true)}>
              <Text style={s.selectorText}>
                {dateTo ? dateTo.toISOString().split('T')[0] : 'Any'}
              </Text>
              <Ionicons name="calendar-outline" size={16} color="#8fa8c8" />
            </TouchableOpacity>
          </View>
        </View>

        {showFrom && (
          <DateTimePicker
            value={dateFrom || new Date()}
            mode="date"
            themeVariant="dark"
            display={Platform.OS === 'ios' ? 'spinner' : 'default'}
            onChange={(_, d) => { setShowFrom(false); if (d) setDateFrom(d); }}
          />
        )}
        {showTo && (
          <DateTimePicker
            value={dateTo || new Date()}
            mode="date"
            themeVariant="dark"
            display={Platform.OS === 'ios' ? 'spinner' : 'default'}
            onChange={(_, d) => { setShowTo(false); if (d) setDateTo(d); }}
          />
        )}

        {/* Clear filters */}
        {(searchName || roomFilter.value || dateFrom || dateTo) && (
          <TouchableOpacity
            style={s.clearBtn}
            onPress={() => { setSearchName(''); setRoomFilter(ROOM_FILTERS[0]); setDateFrom(null); setDateTo(null); }}
          >
            <Ionicons name="close-circle-outline" size={14} color="#8fa8c8" />
            <Text style={s.clearText}>Clear filters</Text>
          </TouchableOpacity>
        )}

        {/* Search button */}
        <TouchableOpacity style={[s.searchBtn, loading && s.disabled]} onPress={handleSearch} disabled={loading}>
          {loading
            ? <ActivityIndicator color="#fff" size="small" />
            : <Text style={s.searchBtnText}>Search</Text>
          }
        </TouchableOpacity>

        {/* Results */}
        {searched && (
          <View style={s.results}>
            <Text style={s.resultsCount}>
              {results.length} booking{results.length !== 1 ? 's' : ''} found
            </Text>
            {results.length === 0 ? (
              <View style={s.emptyBox}>
                <Ionicons name="calendar-outline" size={32} color="#4a6080" />
                <Text style={s.emptyText}>No bookings match your filters.</Text>
              </View>
            ) : (
              results.map((b) => (
                <View key={b.id} style={s.resultCard}>
                  <View style={s.resultLeft}>
                    <Text style={s.resultDate}>{b.date}</Text>
                    <Text style={s.resultRoom}>{b.room_name}</Text>
                    <Text style={s.resultTime}>{b.start_time} – {b.end_time}</Text>
                    <Text style={s.resultWho}>{b.booked_by}</Text>
                    {b.purpose ? <Text style={s.resultPurpose}>{b.purpose}</Text> : null}
                  </View>
                  {b.can_cancel && (
                    <TouchableOpacity style={s.cancelBtn} onPress={() => handleCancel(b.id, b.booked_by)}>
                      <Ionicons name="trash-outline" size={16} color="#f87171" />
                    </TouchableOpacity>
                  )}
                </View>
              ))
            )}
          </View>
        )}
      </ScrollView>

      {/* Room filter modal */}
      <Modal visible={roomModal} transparent animationType="slide" onRequestClose={() => setRoomModal(false)}>
        <TouchableOpacity style={pm.backdrop} activeOpacity={1} onPress={() => setRoomModal(false)}>
          <View style={pm.sheet}>
            <View style={pm.handle} />
            <Text style={pm.title}>Filter by Room</Text>
            <FlatList
              data={ROOM_FILTERS}
              keyExtractor={(i) => String(i.value)}
              renderItem={({ item }) => (
                <TouchableOpacity
                  style={[pm.item, item.value === roomFilter.value && pm.itemActive]}
                  onPress={() => { setRoomFilter(item); setRoomModal(false); }}
                >
                  <Text style={[pm.itemText, item.value === roomFilter.value && pm.itemActiveText]}>
                    {item.label}
                  </Text>
                  {item.value === roomFilter.value && <Ionicons name="checkmark" size={16} color="#00AFEF" />}
                </TouchableOpacity>
              )}
            />
          </View>
        </TouchableOpacity>
      </Modal>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe:    { flex: 1, backgroundColor: '#040e1f' },
  root:    { flex: 1, backgroundColor: '#040e1f' },
  content: { padding: 20, paddingBottom: 48 },
  title:   { color: '#f7f4ed', fontSize: 24, fontWeight: '700', marginBottom: 4 },
  sub:     { color: '#8fa8c8', fontSize: 14, marginBottom: 24 },
  label:   { color: '#8fa8c8', fontSize: 13, fontWeight: '600', marginBottom: 6 },
  inputRow:{ position: 'relative', marginBottom: 16 },
  inputIcon:{ position: 'absolute', left: 14, top: 13, zIndex: 1 },
  input: {
    backgroundColor: 'rgba(255,255,255,0.05)', borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)', borderRadius: 12,
    color: '#f7f4ed', fontSize: 15,
    paddingHorizontal: 40, paddingVertical: 12,
  },
  selector: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    backgroundColor: 'rgba(255,255,255,0.05)', borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)', borderRadius: 12,
    paddingHorizontal: 14, paddingVertical: 13, marginBottom: 16,
  },
  selectorText: { color: '#f7f4ed', fontSize: 15 },
  dateRow: { flexDirection: 'row', gap: 12 },
  dateCol: { flex: 1 },
  clearBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 5,
    marginBottom: 14, alignSelf: 'flex-start',
  },
  clearText: { color: '#8fa8c8', fontSize: 13 },
  searchBtn: {
    backgroundColor: '#00AFEF', borderRadius: 14,
    paddingVertical: 14, alignItems: 'center',
    shadowColor: '#00AFEF', shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.3, shadowRadius: 12, elevation: 5,
    marginBottom: 24,
  },
  searchBtnText: { color: '#fff', fontSize: 15, fontWeight: '700' },
  disabled: { opacity: 0.6 },
  results: {},
  resultsCount: { color: '#8fa8c8', fontSize: 13, marginBottom: 12 },
  emptyBox: { alignItems: 'center', paddingVertical: 32, gap: 10 },
  emptyText: { color: '#4a6080', fontSize: 14 },
  resultCard: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: 14, borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.07)',
    padding: 14, marginBottom: 10,
  },
  resultLeft:    { flex: 1 },
  resultDate:    { color: '#60a5fa', fontSize: 11, fontWeight: '600', marginBottom: 3 },
  resultRoom:    { color: '#e2e8f0', fontSize: 14, fontWeight: '600', marginBottom: 2 },
  resultTime:    { color: '#93c5fd', fontSize: 13, marginBottom: 2 },
  resultWho:     { color: '#94a3b8', fontSize: 13 },
  resultPurpose: { color: '#64748b', fontSize: 12, marginTop: 2 },
  cancelBtn: {
    backgroundColor: 'rgba(239,68,68,0.1)', borderRadius: 8,
    width: 34, height: 34, alignItems: 'center', justifyContent: 'center',
  },
});

const pm = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: '#071629', borderTopLeftRadius: 24, borderTopRightRadius: 24,
    paddingBottom: 32,
  },
  handle: {
    width: 40, height: 4, backgroundColor: 'rgba(255,255,255,0.2)',
    borderRadius: 2, alignSelf: 'center', marginTop: 12, marginBottom: 16,
  },
  title:          { color: '#f7f4ed', fontSize: 16, fontWeight: '700', paddingHorizontal: 20, marginBottom: 8 },
  item: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 20, paddingVertical: 14,
    borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.05)',
  },
  itemActive:     { backgroundColor: 'rgba(0,175,239,0.08)' },
  itemText:       { color: '#94a3b8', fontSize: 15 },
  itemActiveText: { color: '#00AFEF', fontWeight: '600' },
});
