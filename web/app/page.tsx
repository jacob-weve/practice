import { redirect } from "next/navigation";

// 로그인 여부는 각 화면이 확인한다(Access Token이 메모리에만 있어 서버에서는 알 수 없음).
export default function HomePage() {
  redirect("/transform");
}
