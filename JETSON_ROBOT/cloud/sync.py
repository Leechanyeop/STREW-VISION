

class CloudSync:

    def __init__(self, cloud_client):
        self.cloud_client = cloud_client
        self.fail_queue =[]  # 실패한 보고를 저장하는 큐입니다.

    def try_send(self, report_func, *args,**kwargs): 

        # AWS 클라우드에 보고하는 함수를 호출하고, 실패하면 큐에 넣는 메서드입니다.
        try:
            report_func(*args,**kwargs)
            print("Report '" + str(report_func.__name__) + "' successfully.")
            # 성공했을 때 여기서 뭐 더 할 거 있을까?

        except Exception as e:
            print(f"Failed to send report: {e}. Queuing for retry.")
            # 실패했을 때 큐에 넣는 로직을 구현해야 합니다.
            # 예를 들어, self.fail_queue.append((report_func, args)) 같은 식으로 큐에 넣을 수 있습니다.
            self.fail_queue.append((report_func,args,kwargs))


    def flush_queue(self):
        
        while self.fail_queue:
           
            re_try_func = self.fail_queue.pop(0)

            try:
                re_try_func[0](*re_try_func[1],**re_try_func[2])  # 큐에서 꺼낸 함수와 인자를 사용하여 재시도합니다.
               
                print("Retry report '" + str(re_try_func[0].__name__) + "' successfully.")
                
            except Exception as e:

                print(f"Failed to retry report: {e}.")
                self.fail_queue.append(re_try_func)  # 재시도에도 실패하면 다시 큐에 넣습니다.
            