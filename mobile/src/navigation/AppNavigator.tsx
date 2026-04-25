import React from 'react';
import { View, Text, ActivityIndicator, StyleSheet } from 'react-native';
import { NavigationContainer, DefaultTheme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../context/AuthContext';
import LoginScreen    from '../screens/LoginScreen';
import HomeScreen     from '../screens/HomeScreen';
import BookRoomScreen from '../screens/BookRoomScreen';
import ScheduleScreen from '../screens/ScheduleScreen';
import HistoryScreen  from '../screens/HistoryScreen';
import ProfileScreen  from '../screens/ProfileScreen';

const Stack = createNativeStackNavigator();
const Tab   = createBottomTabNavigator();

const NAV_THEME = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    background: '#040e1f',
    card:       '#040e1f',
    border:     'rgba(255,255,255,0.08)',
    text:       '#f7f4ed',
    primary:    '#00AFEF',
  },
};

type TabIcon = 'home' | 'calendar' | 'list' | 'time' | 'person';

function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarStyle: {
          backgroundColor: '#071629',
          borderTopColor: 'rgba(255,255,255,0.08)',
          borderTopWidth: 1,
          height: 60,
          paddingBottom: 8,
        },
        tabBarActiveTintColor:   '#00AFEF',
        tabBarInactiveTintColor: '#4a6080',
        tabBarLabelStyle: { fontSize: 11, fontWeight: '600' },
        tabBarIcon: ({ focused, color, size }) => {
          const icons: Record<string, [TabIcon, TabIcon]> = {
            Home:     ['home',          'home-outline'],
            Book:     ['calendar',      'calendar-outline'],
            Schedule: ['list',          'list-outline'],
            History:  ['time',          'time-outline'],
            Profile:  ['person',        'person-outline'],
          };
          const [active, inactive] = icons[route.name] ?? ['home', 'home-outline'];
          return <Ionicons name={(focused ? active : inactive) as any} size={22} color={color} />;
        },
      })}
    >
      <Tab.Screen name="Home"     component={HomeScreen}     options={{ title: 'Status' }} />
      <Tab.Screen name="Book"     component={BookRoomScreen} options={{ title: 'Book' }} />
      <Tab.Screen name="Schedule" component={ScheduleScreen} options={{ title: 'Schedule' }} />
      <Tab.Screen name="History"  component={HistoryScreen}  options={{ title: 'History' }} />
      <Tab.Screen name="Profile"  component={ProfileScreen}  options={{ title: 'Profile' }} />
    </Tab.Navigator>
  );
}

export default function AppNavigator() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <View style={s.loading}>
        <ActivityIndicator size="large" color="#00AFEF" />
      </View>
    );
  }

  return (
    <NavigationContainer theme={NAV_THEME}>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {user
          ? <Stack.Screen name="Main" component={MainTabs} />
          : <Stack.Screen name="Login" component={LoginScreen} />
        }
      </Stack.Navigator>
    </NavigationContainer>
  );
}

const s = StyleSheet.create({
  loading: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#040e1f' },
});
