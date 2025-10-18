import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD
import threading
import httpx
import random
import re
import time
from datetime import datetime
import os
from PIL import Image, ImageTk, ImageDraw
import pystray
from pystray import MenuItem as item


class CookieRefresher:
    def __init__(self):
        self.working_proxies = []
        self.results = []
        
    def load_file(self, filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    
    def format_proxy(self, proxy_string):
        if not proxy_string.startswith("http://"):
            return f"http://{proxy_string}"
        return proxy_string
    
    def check_proxy(self, proxy_string):
        try:
            proxy_formatted = self.format_proxy(proxy_string)
            proxy = {"http://": proxy_formatted, "https://": proxy_formatted}
            timeout = httpx.Timeout(10.0, connect=5.0)
            response = httpx.get("https://www.roblox.com", proxies=proxy, timeout=timeout)
            return response.status_code == 200
        except:
            return False
    
    def check_all_proxies(self, proxies, log_callback):
        log_callback("Checking proxies...\n")
        self.working_proxies = []
        
        for i, proxy in enumerate(proxies, 1):
            log_callback(f"  [{i}/{len(proxies)}] Testing {proxy}... ")
            if self.check_proxy(proxy):
                self.working_proxies.append(proxy)
                log_callback("✓ OK\n")
            else:
                log_callback("✗ Failed\n")
        
        if not self.working_proxies:
            raise Exception("No working proxies found!")
        
        log_callback(f"\n✓ Found {len(self.working_proxies)} working proxies out of {len(proxies)}\n\n")
    
    def get_random_proxy(self):
        if not self.working_proxies:
            raise Exception("No working proxies available!")
        proxy_string = self.format_proxy(random.choice(self.working_proxies))
        return {"http://": proxy_string, "https://": proxy_string}
    
    def generate_csrf_token(self, auth_cookie, proxy):
        csrf_req = httpx.get("https://www.roblox.com/home",
                             cookies={".ROBLOSECURITY": auth_cookie},
                             proxies=proxy,
                             timeout=httpx.Timeout(30.0, connect=10.0),
                             follow_redirects=True)
        
        if csrf_req.status_code not in [200, 302]:
            raise Exception(f"Failed to fetch CSRF token. Status code: {csrf_req.status_code}")
        
        parts = csrf_req.text.split("<meta name=\"csrf-token\" data-token=\"")
        if len(parts) < 2:
            raise Exception("CSRF token not found in response.")
        
        token_parts = parts[1].split("\" />")
        if len(token_parts) < 1:
            raise Exception("Failed to parse CSRF token.")
        
        return token_parts[0]
    
    def refresh_cookie(self, auth_cookie, log_callback, max_retries=5):
        used_proxies = []
        
        for attempt in range(max_retries):
            try:
                available_proxies = [p for p in self.working_proxies if p not in used_proxies]
                if not available_proxies:
                    used_proxies = []
                    available_proxies = self.working_proxies
                
                proxy_str = self.format_proxy(random.choice(available_proxies))
                used_proxies.append(proxy_str)
                proxy = {"http://": proxy_str, "https://": proxy_str}
                
                log_callback(f"[Attempt {attempt + 1}/{max_retries}] Using proxy: {proxy_str}\n")
                
                if attempt > 0:
                    delay = random.uniform(2, 5)
                    log_callback(f"⏱ Waiting {delay:.1f}s before retry...\n")
                    time.sleep(delay)
                
                csrf_token = self.generate_csrf_token(auth_cookie, proxy)
                log_callback(f"CSRF Token: {csrf_token}\n")
                
                time.sleep(random.uniform(1, 2))
                
                headers = {
                    "Content-Type": "application/json",
                    "user-agent": "Roblox/WinInet",
                    "origin": "https://www.roblox.com",
                    "referer": "https://www.roblox.com/my/account",
                    "x-csrf-token": csrf_token
                }
                cookies = {".ROBLOSECURITY": auth_cookie}
                
                req = httpx.post("https://auth.roblox.com/v1/authentication-ticket",
                                headers=headers, cookies=cookies, json={}, proxy=list(proxy.values())[0],
                                timeout=httpx.Timeout(30.0, connect=10.0))
                
                if req.status_code == 401:
                    log_callback(f"✗ Unauthorized (401). Cookie is invalid.\n\n")
                    return None
                
                if req.status_code == 429:
                    log_callback(f"⚠ Rate limited (429). Switching proxy and retrying...\n")
                    time.sleep(random.uniform(3, 6))
                    continue
                
                if "rbx-authentication-ticket" not in req.headers:
                    error_msg = f"Failed to get authentication ticket. Status: {req.status_code}"
                    if req.text:
                        error_msg += f", Response: {req.text[:200]}"
                    raise Exception(error_msg)
                
                auth_ticket = req.headers["rbx-authentication-ticket"]
                log_callback(f"Authentication Ticket: {auth_ticket}\n")
                
                time.sleep(random.uniform(1, 2))
                
                headers.update({"RBXAuthenticationNegotiation": "1"})
                
                req1 = httpx.post("https://auth.roblox.com/v1/authentication-ticket/redeem",
                                headers=headers, json={"authenticationTicket": auth_ticket}, proxy=list(proxy.values())[0],
                                timeout=httpx.Timeout(30.0, connect=10.0))
                
                if req1.status_code == 401:
                    log_callback(f"✗ Unauthorized (401). Cookie is invalid.\n\n")
                    return None
                
                if req1.status_code == 429:
                    log_callback(f"⚠ Rate limited (429). Switching proxy and retrying...\n")
                    time.sleep(random.uniform(3, 6))
                    continue
                
                if "set-cookie" not in req1.headers:
                    error_msg = f"Failed to get new auth cookie. Status: {req1.status_code}"
                    if req1.text:
                        error_msg += f", Response: {req1.text[:200]}"
                    raise Exception(error_msg)
                
                match = re.search(r"\.ROBLOSECURITY=(.*?);", req1.headers["set-cookie"])
                if not match:
                    raise Exception("Failed to parse new auth cookie")
                
                new_cookie = match.group(1)
                log_callback(f"✓ SUCCESS - New Cookie Generated\n\n")
                
                time.sleep(random.uniform(2, 4))
                
                return new_cookie
                
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ProxyError, ConnectionError) as e:
                error_type = type(e).__name__
                log_callback(f"✗ Proxy error ({error_type}): {str(e)[:100]}\n")
                
                if attempt < max_retries - 1:
                    log_callback(f"→ Switching to another proxy...\n")
                    continue
                else:
                    log_callback(f"✗ Failed after {max_retries} attempts\n\n")
                    return None
            
            except Exception as e:
                log_callback(f"✗ ERROR: {str(e)[:200]}\n")
                
                if "401" in str(e) or "Unauthorized" in str(e):
                    log_callback(f"✗ Cookie is invalid (Unauthorized).\n\n")
                    return None
                
                if "429" in str(e) or "Too many requests" in str(e):
                    if attempt < max_retries - 1:
                        log_callback(f"→ Rate limited, switching proxy...\n")
                        continue
                
                if attempt < max_retries - 1:
                    log_callback(f"→ Retrying with another proxy...\n")
                    continue
                else:
                    log_callback(f"✗ Failed after {max_retries} attempts\n\n")
                    return None
        
        return None


class CookieRefresherGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Vexcel Cookie Refresher")
        self.root.geometry("900x700")
        
        self.root.resizable(False, False)
        
        self.bg_color = "#0a0a0a"
        self.fg_color = "#ffffff"
        self.accent_color = "#dc143c"
        self.accent_hover = "#ff1744"
        self.dark_gray = "#1a1a1a"
        self.light_gray = "#2a2a2a"
        
        self.root.configure(bg=self.bg_color)
        
        self.icon_image = self.set_icon()
        
        self.tray_icon = None
        self.setup_tray_icon()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.proxies_file = None
        self.cookies_file = None
        self.refresher = CookieRefresher()
        
        self.create_widgets()
    
    def set_icon(self):
        icon_img = None
        try:
            if os.path.exists("ico.ico"):
                self.root.iconbitmap("ico.ico")
                icon_img = Image.open("ico.ico")
            elif os.path.exists("ico.png"):
                img = Image.open("ico.png")
                img = img.resize((256, 256), Image.Resampling.LANCZOS)
                img.save("ico.ico", format="ICO", sizes=[(256, 256)])
                self.root.iconbitmap("ico.ico")
                icon_img = img
            else:
                icon_img = self.create_default_icon()
        except Exception as e:
            print(f"Could not set icon: {e}")
            icon_img = self.create_default_icon()
        
        return icon_img
    
    def create_default_icon(self):
        img = Image.new('RGB', (256, 256), color='black')
        draw = ImageDraw.Draw(img)
        draw.polygon([(64, 64), (128, 192), (192, 64), (192, 96), (128, 224), (64, 96)], 
                     fill='#dc143c')
        return img
    
    def setup_tray_icon(self):
        try:
            if self.icon_image:
                tray_img = self.icon_image.resize((64, 64), Image.Resampling.LANCZOS)
                
                menu = pystray.Menu(
                    item('Show', self.show_window, default=True),
                    item('Hide', self.hide_window),
                    pystray.Menu.SEPARATOR,
                    item('Exit', self.quit_app)
                )
                
                self.tray_icon = pystray.Icon("vexcel", tray_img, "Vexcel Cookie Refresher", menu)
                
                threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            print(f"Could not create tray icon: {e}")
    
    def show_window(self, icon=None, item=None):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
    
    def hide_window(self, icon=None, item=None):
        self.root.withdraw()
    
    def on_closing(self):
        if self.tray_icon:
            self.hide_window()
        else:
            self.quit_app()
    
    def quit_app(self, icon=None, item=None):
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.quit()
        self.root.destroy()
    
    def create_widgets(self):
        title = tk.Label(self.root, text="VEXCEL COOKIE REFRESHER", 
                        font=("Arial Black", 22, "bold"), fg=self.accent_color, bg=self.bg_color)
        title.pack(pady=25)
        
        subtitle = tk.Label(self.root, text="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", 
                           fg=self.accent_color, bg=self.bg_color, font=("Courier", 8))
        subtitle.pack()
        
        drop_frame = tk.Frame(self.root, bg=self.bg_color)
        drop_frame.pack(pady=15, padx=20, fill=tk.X)
        
        proxies_frame = tk.LabelFrame(drop_frame, text="◆ PROXIES FILE", 
                                     font=("Arial", 11, "bold"), 
                                     fg=self.accent_color, bg=self.bg_color,
                                     padx=10, pady=10, relief=tk.GROOVE, bd=2)
        proxies_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        
        self.proxies_label = tk.Label(proxies_frame, text="⇓ DROP PROXIES HERE ⇓\n━━━━━━━━━━━━━━━━━\nproxies.txt",
                                      bg=self.dark_gray, fg="#666666", relief=tk.GROOVE, 
                                      height=5, width=28, font=("Arial", 10, "bold"), bd=3)
        self.proxies_label.pack(pady=5)
        self.proxies_label.drop_target_register(DND_FILES)
        self.proxies_label.dnd_bind('<<Drop>>', lambda e: self.drop_proxies(e))
        
        cookies_frame = tk.LabelFrame(drop_frame, text="◆ COOKIES FILE", 
                                     font=("Arial", 11, "bold"),
                                     fg=self.accent_color, bg=self.bg_color,
                                     padx=10, pady=10, relief=tk.GROOVE, bd=2)
        cookies_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        
        self.cookies_label = tk.Label(cookies_frame, text="⇓ DROP COOKIES HERE ⇓\n━━━━━━━━━━━━━━━━━\ncookies.txt",
                                     bg=self.dark_gray, fg="#666666", relief=tk.GROOVE, 
                                     height=5, width=28, font=("Arial", 10, "bold"), bd=3)
        self.cookies_label.pack(pady=5)
        self.cookies_label.drop_target_register(DND_FILES)
        self.cookies_label.dnd_bind('<<Drop>>', lambda e: self.drop_cookies(e))
        
        button_frame = tk.Frame(self.root, bg=self.bg_color)
        button_frame.pack(pady=20)
        
        self.start_button = tk.Button(button_frame, text="▶ START REFRESHING", 
                                     command=self.start_refresh,
                                     font=("Arial Black", 13, "bold"), 
                                     bg=self.accent_color, fg="#ffffff",
                                     activebackground=self.accent_hover, activeforeground="#ffffff",
                                     disabledforeground="#ffffff",
                                     height=2, width=25, state=tk.DISABLED,
                                     relief=tk.RAISED, bd=3, cursor="hand2")
        self.start_button.pack()
        
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("red.Horizontal.TProgressbar", 
                       background=self.accent_color, 
                       troughcolor=self.dark_gray,
                       bordercolor=self.bg_color,
                       lightcolor=self.accent_color,
                       darkcolor=self.accent_color)
        
        self.progress = ttk.Progressbar(self.root, mode='indeterminate', 
                                       style="red.Horizontal.TProgressbar")
        self.progress.pack(pady=5, padx=20, fill=tk.X)
        
        log_frame = tk.LabelFrame(self.root, text="◆ SYSTEM LOG", 
                                 font=("Arial", 11, "bold"),
                                 fg=self.accent_color, bg=self.bg_color,
                                 relief=tk.GROOVE, bd=2)
        log_frame.pack(pady=15, padx=20, fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, 
                                                  font=("Consolas", 10), 
                                                  bg=self.dark_gray, 
                                                  fg="#00ff00",
                                                  insertbackground=self.accent_color,
                                                  selectbackground=self.accent_color,
                                                  relief=tk.FLAT)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.log_text.tag_config("error", foreground=self.accent_color)
        self.log_text.tag_config("success", foreground="#00ff00")
        self.log_text.tag_config("info", foreground="#ffffff")
        
        self.status_label = tk.Label(self.root, text="◆ Ready. Drop files to begin.", 
                                    relief=tk.FLAT, anchor=tk.W,
                                    bg=self.light_gray, fg=self.fg_color,
                                    font=("Arial", 9), padx=10, pady=5)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)
    
    def drop_proxies(self, event):
        file_path = event.data.strip('{}')
        self.proxies_file = file_path
        filename = os.path.basename(file_path)
        self.proxies_label.config(text=f"✓ LOADED ✓\n━━━━━━━━━━━━━━━━━\n{filename}", 
                                 bg=self.accent_color, fg="white")
        self.log(f"✓ Loaded proxies file: {file_path}\n", "success")
        self.check_ready()
    
    def drop_cookies(self, event):
        file_path = event.data.strip('{}')
        self.cookies_file = file_path
        filename = os.path.basename(file_path)
        self.cookies_label.config(text=f"✓ LOADED ✓\n━━━━━━━━━━━━━━━━━\n{filename}", 
                                 bg=self.accent_color, fg="white")
        self.log(f"✓ Loaded cookies file: {file_path}\n", "success")
        self.check_ready()
    
    def check_ready(self):
        if self.proxies_file and self.cookies_file:
            self.start_button.config(state=tk.NORMAL, bg=self.accent_hover)
            self.status_label.config(text="◆ Ready to start! Click START REFRESHING button.")
    
    def log(self, message, tag="info"):
        self.log_text.insert(tk.END, message, tag)
        self.log_text.see(tk.END)
        self.root.update()
    
    def start_refresh(self):
        self.start_button.config(state=tk.DISABLED, bg=self.dark_gray)
        self.progress.start()
        self.log_text.delete(1.0, tk.END)
        self.log("="*60 + "\n", "info")
        self.log("◆ VEXCEL COOKIE REFRESHER STARTING...\n", "info")
        self.log("="*60 + "\n\n", "info")
        
        thread = threading.Thread(target=self.refresh_all, daemon=True)
        thread.start()
    
    def refresh_all(self):
        try:
            self.status_label.config(text="Loading files...")
            
            proxies = self.refresher.load_file(self.proxies_file)
            cookies = self.refresher.load_file(self.cookies_file)
            
            self.log(f"Loaded {len(proxies)} proxies\n")
            self.log(f"Loaded {len(cookies)} cookies\n\n")
            
            self.status_label.config(text="Checking proxies...")
            self.refresher.check_all_proxies(proxies, self.log)
            
            results = []
            successful = 0
            failed = 0
            
            for i, cookie in enumerate(cookies, 1):
                self.status_label.config(text=f"Refreshing cookie {i}/{len(cookies)}...")
                self.log(f"{'='*60}\n")
                self.log(f"Cookie #{i}/{len(cookies)}\n")
                self.log(f"{'='*60}\n")
                
                new_cookie = self.refresher.refresh_cookie(cookie, self.log)
                
                if new_cookie:
                    results.append(new_cookie)
                    successful += 1
                else:
                    results.append(f"FAILED: {cookie[:50]}...")
                    failed += 1
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"vexcel-{timestamp}.txt"
            
            with open(filename, "w", encoding="utf-8") as f:
                for result in results:
                    if not result.startswith("FAILED:"):
                        if result.startswith("_|WARNING:"):
                            f.write(f"{result}\n")
                        else:
                            f.write(f"_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you-and-to-steal-your-ROBUX-and-items.|_{result}\n")
            
            self.log(f"\n{'='*60}\n", "info")
            self.log(f"◆ COMPLETE!\n", "success")
            self.log(f"{'='*60}\n", "info")
            self.log(f"✓ Successful: {successful}/{len(cookies)}\n", "success")
            if failed > 0:
                self.log(f"✗ Failed: {failed}/{len(cookies)}\n", "error")
            self.log(f"\n◆ Results saved to: {filename}\n", "info")
            
            self.progress.stop()
            self.status_label.config(text=f"◆ Complete! Results saved to {filename}", fg="#00ff00")
            
            messagebox.showinfo("Complete!", 
                              f"Cookie refresh complete!\n\n"
                              f"Successful: {successful}\n"
                              f"Failed: {failed}\n\n"
                              f"Results saved to:\n{filename}")
            
        except Exception as e:
            self.log(f"\n\n✗ FATAL ERROR: {str(e)}\n", "error")
            self.progress.stop()
            self.status_label.config(text="◆ Error occurred!", fg=self.accent_color)
            messagebox.showerror("Error", f"An error occurred:\n{str(e)}")
        
        finally:
            self.start_button.config(state=tk.NORMAL, bg=self.accent_color)


if __name__ == "__main__":
    root = TkinterDnD.Tk()
    app = CookieRefresherGUI(root)
    root.mainloop()
