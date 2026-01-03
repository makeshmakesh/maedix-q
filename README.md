# maedix-q


Test Cards for Indian Payments

Card Network	Card Number	
Mastercard	    2305 3242 5784 8228	
Visa	        4386 2894 0766 0153	


Test Cards for International Payments
Card Network	Card Number	CVV	Expiry Date
Mastercard	    5421 1393 0609 0628
                5105 1051 0510 5100	
Visa	        4012 8888 8888 1881
                5104 0600 0000 0008	




Restart after change in ec2

sudo systemctl restart nginx
sudo systemctl restart gunicorn


  Usage-based features (with limits)

  | Feature Code | Description                | Used In                     |
  |--------------|----------------------------|-----------------------------|
  | quiz_attempt | Quiz attempts per month    | quiz/views.py:122, 128      |
  | video_gen    | Video generation from quiz | quiz/views.py:808, 834, 839 |
  | quiz_create  | Create custom quizzes      | quiz/views.py:968, 986, 994 |

  Boolean features (no limits)

  | Feature Code                       | Description                        | Used In                          |
  |------------------------------------|------------------------------------|----------------------------------|
  | custom_handle_name_in_video_export | Custom handle name in video export | quiz/views.py:812, 860           |
  | analytics                          | Advanced analytics                 | Defined in subscription_utils.py |
  | certificates                       | Completion certificates            | Defined in subscription_utils.py |

  Feature structure

  Features are stored as JSON in the Plan model with this structure:
  # With limit (usage-based)
  {"code": "video_gen", "limit": 5, "description": "Video generation from quiz"}

  # Without limit (boolean feature)
  {"code": "custom_handle_name_in_video_export", "description": "Custom handle name"}