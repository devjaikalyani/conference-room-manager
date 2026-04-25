import React, { useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  KeyboardAvoidingView, Platform, ScrollView, ActivityIndicator, Alert,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../context/AuthContext';

export default function LoginScreen() {
  const { login } = useAuth();
  const [code, setCode]             = useState('');
  const [password, setPassword]     = useState('');
  const [showPass, setShowPass]     = useState(false);
  const [loading, setLoading]       = useState(false);

  const handleLogin = async () => {
    if (!code.trim()) return Alert.alert('Required', 'Please enter your Employee Code.');
    if (!password)    return Alert.alert('Required', 'Please enter your password.');
    setLoading(true);
    try {
      await login(code.trim(), password);
    } catch (e: any) {
      Alert.alert('Sign In Failed', e.message || 'Invalid credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <LinearGradient colors={['#000f28', '#001a3a', '#003058']} style={s.root}>
      <SafeAreaView style={s.safe}>
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={s.kav}
        >
          <ScrollView
            contentContainerStyle={s.scroll}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            {/* ── Brand hero ───────────────────────────────────────── */}
            <View style={s.hero}>
              <View style={s.logoRow}>
                <View style={s.logoBox}>
                  <Text style={s.logoLetters}>RWS</Text>
                </View>
                <View>
                  <Text style={s.companyName}>RiteWater Solutions</Text>
                  <Text style={s.kicker}>EMPLOYEE PORTAL</Text>
                </View>
              </View>
              <Text style={s.heroTitle}>Conference Room{'\n'}Manager</Text>
              <Text style={s.heroSub}>
                Book and manage conference rooms{'\n'}effortlessly from your phone.
              </Text>

              <View style={s.features}>
                {['Live room availability', 'Instant booking', 'Today\'s schedule'].map((f) => (
                  <View key={f} style={s.featureRow}>
                    <Ionicons name="checkmark-circle" size={15} color="#00AFEF" />
                    <Text style={s.featureText}>{f}</Text>
                  </View>
                ))}
              </View>
            </View>

            {/* ── Auth card ────────────────────────────────────────── */}
            <View style={s.card}>
              <Text style={s.cardTitle}>Welcome back</Text>
              <Text style={s.cardSub}>Sign in to access the portal.</Text>

              {/* Employee Code */}
              <Text style={s.label}>Employee Code</Text>
              <TextInput
                style={s.input}
                placeholder="e.g. RWSIPL007 or TRWSIPL010"
                placeholderTextColor="#3a5070"
                value={code}
                onChangeText={setCode}
                autoCapitalize="characters"
                autoCorrect={false}
                returnKeyType="next"
              />

              {/* Password */}
              <Text style={s.label}>Password</Text>
              <View style={s.passRow}>
                <TextInput
                  style={[s.input, s.passInput]}
                  placeholder="••••••••"
                  placeholderTextColor="#3a5070"
                  value={password}
                  onChangeText={setPassword}
                  secureTextEntry={!showPass}
                  returnKeyType="done"
                  onSubmitEditing={handleLogin}
                />
                <TouchableOpacity style={s.eyeBtn} onPress={() => setShowPass(!showPass)}>
                  <Ionicons name={showPass ? 'eye-off-outline' : 'eye-outline'} size={20} color="#8fa8c8" />
                </TouchableOpacity>
              </View>

              {/* Sign In */}
              <TouchableOpacity
                style={[s.signInBtn, loading && s.signInBtnDisabled]}
                onPress={handleLogin}
                disabled={loading}
                activeOpacity={0.85}
              >
                {loading
                  ? <ActivityIndicator color="#fff" />
                  : <Text style={s.signInText}>Sign in</Text>
                }
              </TouchableOpacity>

              {/* Hint */}
              <View style={s.hintBox}>
                <Ionicons name="information-circle-outline" size={14} color="#8fa8c8" />
                <Text style={s.hintText}>
                  Default password is your Employee Code. You will be prompted to change it after first login.
                </Text>
              </View>
            </View>
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </LinearGradient>
  );
}

const s = StyleSheet.create({
  root:   { flex: 1 },
  safe:   { flex: 1 },
  kav:    { flex: 1 },
  scroll: { flexGrow: 1, paddingHorizontal: 20, paddingVertical: 28 },

  // Hero
  hero: { marginBottom: 24 },
  logoRow: {
    flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 20,
  },
  logoBox: {
    backgroundColor: '#00AFEF', borderRadius: 10, width: 44, height: 44,
    alignItems: 'center', justifyContent: 'center',
  },
  logoLetters: { color: '#fff', fontSize: 13, fontWeight: '800', letterSpacing: 0.5 },
  companyName: { color: '#f0f6fc', fontSize: 14, fontWeight: '700' },
  kicker: {
    color: '#00AFEF', fontSize: 10, fontWeight: '700',
    letterSpacing: 1.4, textTransform: 'uppercase', marginTop: 1,
  },
  heroTitle: {
    color: '#f0f6fc', fontSize: 30, fontWeight: '800',
    lineHeight: 36, marginBottom: 10,
  },
  heroSub: { color: '#8fa8c8', fontSize: 14, lineHeight: 21, marginBottom: 20 },
  features: { gap: 8 },
  featureRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  featureText: { color: '#a8c8e0', fontSize: 13 },

  // Card
  card: {
    backgroundColor: 'rgba(4,20,48,0.92)',
    borderRadius: 22,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
    padding: 24,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 16 },
    shadowOpacity: 0.3,
    shadowRadius: 32,
    elevation: 12,
  },
  cardTitle: {
    color: '#f7f4ed', fontSize: 26, fontWeight: '700', marginBottom: 4,
  },
  cardSub: { color: '#8fa8c8', fontSize: 14, marginBottom: 22 },

  // Inputs
  label: { color: '#8fa8c8', fontSize: 13, fontWeight: '600', marginBottom: 6 },
  input: {
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)',
    borderRadius: 12,
    color: '#f7f4ed',
    fontSize: 15,
    paddingHorizontal: 14,
    paddingVertical: 12,
    marginBottom: 16,
  },
  passRow: { position: 'relative', marginBottom: 20 },
  passInput: { marginBottom: 0, paddingRight: 48 },
  eyeBtn: {
    position: 'absolute', right: 14, top: 12,
  },

  // Sign In button
  signInBtn: {
    backgroundColor: '#00AFEF',
    borderRadius: 14,
    paddingVertical: 14,
    alignItems: 'center',
    shadowColor: '#00AFEF',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.35,
    shadowRadius: 16,
    elevation: 6,
    marginBottom: 16,
  },
  signInBtnDisabled: { opacity: 0.7 },
  signInText: { color: '#fff', fontSize: 16, fontWeight: '700' },

  // Hint
  hintBox: {
    flexDirection: 'row', alignItems: 'flex-start', gap: 6,
    backgroundColor: 'rgba(255,255,255,0.03)',
    borderRadius: 10, padding: 10,
  },
  hintText: { color: '#8fa8c8', fontSize: 12, lineHeight: 17, flex: 1 },
});
