import { getApp, getApps, initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

const firebaseConfig = {
  apiKey: "AIzaSyCKO2AHeof6XpJ1_VHYWRHNBkA4hOlsaKQ",
  authDomain: "a3-voting-system-dev.firebaseapp.com",
  projectId: "a3-voting-system-dev",
  storageBucket: "a3-voting-system-dev.firebasestorage.app",
  messagingSenderId: "303620866810",
  appId: "1:303620866810:web:f146a26d686d8b9a72ff43",
};

const app = getApps().length > 0 ? getApp() : initializeApp(firebaseConfig);

export const auth = getAuth(app);
export const db = getFirestore(app);